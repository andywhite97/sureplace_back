import json
import logging
import re
import socket
import uuid
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailAddress:
    email: str
    name: str = ""


@dataclass(frozen=True)
class EmailMessage:
    to: list[EmailAddress]
    subject: str
    text: str = ""
    html: str = ""
    from_email: str = ""
    from_name: str = ""
    cc: list[EmailAddress] = field(default_factory=list)
    bcc: list[EmailAddress] = field(default_factory=list)
    reply_to: list[EmailAddress] = field(default_factory=list)
    template_key: str = "transactional"
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    idempotency_key: str = ""


@dataclass(frozen=True)
class EmailProviderResult:
    provider: str
    provider_message_id: str
    status: str


class EmailProviderError(Exception):
    retryable = False

    def __init__(self, message: str, *, status_code: int | None=None, code: str="", request_id: str=""):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.safe_message = message


class RetryableEmailProviderError(EmailProviderError):
    retryable = True


class PermanentEmailProviderError(EmailProviderError):
    retryable = False


class ConfigurationEmailProviderError(PermanentEmailProviderError):
    pass


class EmailProvider:
    provider = "base"

    def send(self, message: EmailMessage) -> EmailProviderResult:
        raise NotImplementedError


class DjangoEmailProvider(EmailProvider):
    provider = "django"

    def send(self, message: EmailMessage) -> EmailProviderResult:
        django_message = EmailMultiAlternatives(
            message.subject,
            message.text,
            format_sender(message.from_email, message.from_name),
            [address.email for address in message.to],
            cc=[address.email for address in message.cc],
            bcc=[address.email for address in message.bcc],
            reply_to=[address.email for address in message.reply_to],
        )
        if message.html:
            django_message.attach_alternative(message.html, "text/html")
        django_message.send()
        return EmailProviderResult(provider=self.provider, provider_message_id="", status="accepted")


class BirdEmailProvider(EmailProvider):
    provider = "bird"
    endpoint = "/v1/email/messages"
    supported_regions = {"us1", "eu1"}

    def __init__(self):
        self.api_key = getattr(settings, "BIRD_API_KEY", "")
        self.base_url = resolve_bird_base_url(self.api_key, getattr(settings, "BIRD_API_BASE_URL", ""))
        self.timeout = getattr(settings, "BIRD_REQUEST_TIMEOUT_SECONDS", 10)
        if not self.api_key:
            raise ConfigurationEmailProviderError("BIRD_API_KEY is required when EMAIL_PROVIDER=bird.")

    def send(self, message: EmailMessage) -> EmailProviderResult:
        payload = self._payload(message)
        request = Request(
            self.base_url.rstrip("/") + self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": message.idempotency_key or str(uuid.uuid4()),
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = _read_json(response.read())
                status_code = response.status
        except HTTPError as exc:
            body = _read_json(exc.read())
            raise _bird_error(exc.code, body) from exc
        except (TimeoutError, socket.timeout, URLError) as exc:
            raise RetryableEmailProviderError("Bird email request failed transiently.", code="network_error") from exc

        if status_code != 202:
            raise _bird_error(status_code, body)
        return EmailProviderResult(
            provider=self.provider,
            provider_message_id=str(body.get("id", "")),
            status="accepted",
        )

    def _payload(self, message: EmailMessage) -> dict[str, Any]:
        if not message.html and not message.text:
            raise PermanentEmailProviderError("Email content must include html or text.", code="invalid_content")
        validate_message_addresses(message)
        payload: dict[str, Any] = {
            "from": _address_payload(EmailAddress(message.from_email, message.from_name)),
            "to": [_address_payload(address) for address in message.to],
            "subject": message.subject,
            "category": "transactional",
            "track_opens": getattr(settings, "BIRD_TRACK_OPENS", False),
            "track_clicks": getattr(settings, "BIRD_TRACK_CLICKS", False),
        }
        if message.html:
            payload["html"] = message.html
        if message.text:
            payload["text"] = message.text
        if message.cc:
            payload["cc"] = [_address_payload(address) for address in message.cc]
        if message.bcc:
            payload["bcc"] = [_address_payload(address) for address in message.bcc]
        if message.reply_to:
            payload["reply_to"] = [_address_payload(address) for address in message.reply_to]
        if message.tags:
            payload["tags"] = [
                {"name": key, "value": sanitize_bird_tag_value(value)} for key, value in message.tags.items()
            ]
        if message.metadata:
            payload["metadata"] = message.metadata
        return payload


def get_email_provider() -> EmailProvider:
    provider = getattr(settings, "EMAIL_PROVIDER", "django").lower()
    if provider == "django":
        return DjangoEmailProvider()
    if provider == "bird":
        return BirdEmailProvider()
    raise ConfigurationEmailProviderError(f"Unsupported EMAIL_PROVIDER: {provider}.")


def build_email_message(
    to: str | list[str],
    subject: str,
    text: str,
    html: str="",
    *,
    cc: list[str] | None=None,
    bcc: list[str] | None=None,
    template_key: str="transactional",
    tags: dict[str, str] | None=None,
    metadata: dict[str, str] | None=None,
    idempotency_key: str="",
) -> EmailMessage:
    from_name, from_email = parse_configured_sender()
    reply_to = getattr(settings, "DEFAULT_REPLY_TO_EMAIL", "")
    recipients = [to] if isinstance(to, str) else to
    return EmailMessage(
        to=[parse_email_address(value) for value in recipients],
        cc=[parse_email_address(value) for value in cc or []],
        bcc=[parse_email_address(value) for value in bcc or []],
        subject=subject,
        text=text,
        html=html,
        from_email=from_email,
        from_name=from_name,
        reply_to=[parse_email_address(reply_to)] if reply_to else [],
        template_key=template_key,
        tags=tags or {},
        metadata=metadata or {},
        idempotency_key=idempotency_key,
    )


def parse_configured_sender() -> tuple[str, str]:
    configured = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    parsed_name, parsed_email = parseaddr(configured)
    from_email = parsed_email or configured
    from_name = getattr(settings, "DEFAULT_FROM_NAME", "") or parsed_name
    if not from_email:
        raise ConfigurationEmailProviderError("DEFAULT_FROM_EMAIL is required.")
    return from_name, from_email


def parse_email_address(value: str) -> EmailAddress:
    name, email = parseaddr(value)
    return EmailAddress(email=email or value, name=name)


def validate_message_addresses(message: EmailMessage) -> None:
    addresses = [*message.to, *message.cc, *message.bcc, *message.reply_to]
    addresses.append(EmailAddress(message.from_email, message.from_name))
    for address in addresses:
        try:
            validate_email(address.email)
        except ValidationError as exc:
            raise PermanentEmailProviderError(
                f"Invalid email address for {address.email!r}.", code="invalid_address"
            ) from exc


def format_sender(email: str, name: str="") -> str:
    return f"{name} <{email}>" if name else email


def resolve_bird_base_url(api_key: str, override: str="") -> str:
    if override:
        return validate_bird_base_url(override)
    region = bird_region_from_key(api_key)
    if not region:
        raise ConfigurationEmailProviderError(
            "BIRD_API_KEY must include a supported region such as bk_us1_ or bk_eu1_."
        )
    return f"https://{region}.platform.bird.com"


def bird_region_from_key(api_key: str) -> str:
    parts = api_key.split("_", 2)
    if len(parts) < 3 or parts[0] != "bk" or parts[1] not in BirdEmailProvider.supported_regions:
        return ""
    return parts[1]


def validate_bird_base_url(value: str) -> str:
    parsed = urlparse(value)
    allowed_hosts = {f"{region}.platform.bird.com" for region in BirdEmailProvider.supported_regions}
    if parsed.scheme != "https" or parsed.netloc not in allowed_hosts or parsed.path not in {"", "/"}:
        raise ConfigurationEmailProviderError("BIRD_API_BASE_URL must be a supported Bird HTTPS regional host.")
    return f"https://{parsed.netloc}"


def _address_payload(address: EmailAddress) -> dict[str, str]:
    payload = {"email": address.email}
    if address.name:
        payload["name"] = address.name
    return payload


def sanitize_bird_tag_value(value: Any) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or ""))
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "tag"


def _read_json(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bird_error(status_code: int, body: dict[str, Any]) -> EmailProviderError:
    code, message, request_id, details = _safe_error_details(body)
    if details:
        message = "\n".join([message, *details]) if message else "\n".join(details)
    message = _safe_error_value(message, 500)
    error_cls = RetryableEmailProviderError if status_code == 429 or status_code >= 500 else PermanentEmailProviderError
    return error_cls(
        message or "Bird email request was rejected.",
        status_code=status_code,
        code=code,
        request_id=request_id,
    )


def _safe_error_details(body: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    code = str(error.get("code", "")) if isinstance(error, dict) else ""
    message = str(error.get("message", "")) if isinstance(error, dict) else ""
    request_id = str(error.get("request_id", "")) if isinstance(error, dict) else ""
    details = []
    raw_details = error.get("details", []) if isinstance(error, dict) else []
    if isinstance(raw_details, list):
        for detail in raw_details:
            if not isinstance(detail, dict):
                continue
            param = _safe_error_value(detail.get("param"))
            detail_message = _safe_error_value(detail.get("message"))
            if param and detail_message:
                details.append(f"{param}: {detail_message}")
    return _safe_error_value(code, 100), _safe_error_value(message, 500), _safe_error_value(request_id, 120), details


def _safe_error_value(value: Any, limit: int=500) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    return text[:limit]
