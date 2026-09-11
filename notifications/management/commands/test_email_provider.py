from __future__ import annotations

from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from notifications.email_providers import (
    ConfigurationEmailProviderError,
    EmailProviderError,
    get_email_provider,
    parse_configured_sender,
)
from notifications.email_templates import render_email, sample_context
from notifications.services import enqueue_transactional_email, send_transactional_email

TEMPLATE_KEY = "system.email_diagnostic"
SUBJECT = "SurePlace email delivery test"
MESSAGE = (
    "Your SurePlace email provider is configured correctly. "
    "This diagnostic message was sent manually by a SurePlace administrator. "
    "No action is required."
)
SAFE_DJANGO_BACKENDS = {
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.locmem.EmailBackend",
}


class Command(BaseCommand):
    help = "Safely verify the currently configured SurePlace email provider."

    def add_arguments(self, parser):
        parser.add_argument("recipient")
        parser.add_argument("--dry-run", action="store_true", help="Render and validate without sending or queueing.")
        parser.add_argument("--via-celery", action="store_true", help="Queue the diagnostic through the Celery path.")

    def handle(self, *args, **options):
        recipient = options["recipient"]
        dry_run = options["dry_run"]
        via_celery = options["via_celery"]
        verbosity = int(options.get("verbosity", 1))

        self.validate_recipient(recipient)
        sender = self.validate_sender()
        provider_name = getattr(settings, "EMAIL_PROVIDER", "django").lower()
        backend = getattr(settings, "EMAIL_BACKEND", "")
        provider = self.resolve_provider()
        rendered = render_email(TEMPLATE_KEY, sample_context(TEMPLATE_KEY))

        if verbosity >= 1:
            self.stdout.write(f"Provider: {provider.provider}")
            if provider.provider == "django":
                self.stdout.write(f"Backend: {backend or 'default'}")
            self.stdout.write(f"From: {sender}")
            self.stdout.write(f"Recipient: {recipient}")
            self.warn_if_debug_external_provider(provider_name, backend)

        if verbosity >= 2:
            _, sender_email = parseaddr(sender)
            sender_domain = sender_email.rsplit("@", 1)[-1] if "@" in sender_email else "unavailable"
            self.stdout.write(f"Template: {rendered.template_key}")
            self.stdout.write(f"Sender domain: {sender_domain}")
            self.stdout.write(f"Rendered HTML: {'yes' if rendered.html else 'no'}")
            self.stdout.write(f"Rendered text: {'yes' if rendered.text else 'no'}")
            self.stdout.write(f"Provider class: {provider.__class__.__name__}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run successful."))
            self.stdout.write(f"Provider: {provider.provider}")
            self.stdout.write(f"Template: {rendered.template_key}")
            self.stdout.write("Network call: skipped")
            return

        if via_celery:
            delivery = enqueue_transactional_email(
                recipient,
                SUBJECT,
                MESSAGE,
                "/",
                template_key=TEMPLATE_KEY,
                tags={"category": "system", "purpose": "email_diagnostic"},
                metadata={"purpose": "email_diagnostic"},
                context=sample_context(TEMPLATE_KEY),
            )
            self.stdout.write(self.style.SUCCESS("Diagnostic email queued."))
            self.stdout.write(f"Provider: {provider.provider}")
            self.stdout.write(f"Delivery ID: {delivery.id}")
            return

        try:
            result = send_transactional_email(
                recipient,
                SUBJECT,
                MESSAGE,
                "/",
                template_key=TEMPLATE_KEY,
                tags={"category": "system", "purpose": "email_diagnostic"},
                metadata={"purpose": "email_diagnostic"},
                context=sample_context(TEMPLATE_KEY),
            )
        except EmailProviderError as exc:
            raise CommandError(map_provider_error(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Email provider diagnostic successful."))
        self.stdout.write(f"Provider: {result.provider}")
        self.stdout.write(f"Status: {result.status or 'accepted'}")
        self.stdout.write(f"Message ID: {result.provider_message_id or 'unavailable'}")
        if result.provider == "bird" and result.status == "accepted":
            self.stdout.write("Bird accepted the message for delivery.")

    def validate_recipient(self, recipient: str):
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise CommandError("Invalid recipient email address.") from exc

    def validate_sender(self) -> str:
        try:
            sender_name, sender_email = parse_configured_sender()
            validate_email(sender_email)
        except (ConfigurationEmailProviderError, ValidationError) as exc:
            raise CommandError("Email sender configuration is incomplete or invalid.") from exc
        return f"{sender_name} <{sender_email}>" if sender_name else sender_email

    def resolve_provider(self):
        try:
            return get_email_provider()
        except ConfigurationEmailProviderError as exc:
            raise CommandError(map_provider_error(exc)) from exc

    def warn_if_debug_external_provider(self, provider_name: str, backend: str):
        if not getattr(settings, "DEBUG", False):
            return
        if provider_name == "bird":
            self.stdout.write(
                self.style.WARNING("Warning: DEBUG is enabled and EMAIL_PROVIDER=bird will send externally.")
            )
            return
        if provider_name == "django" and backend and backend not in SAFE_DJANGO_BACKENDS:
            self.stdout.write(
                self.style.WARNING("Warning: DEBUG is enabled and the Django email backend may send externally.")
            )


def map_provider_error(error: EmailProviderError) -> str:
    status_code = error.status_code
    message = (error.safe_message or "").lower()
    code = (error.code or "").lower()

    if isinstance(error, ConfigurationEmailProviderError):
        return str(error)
    if status_code == 401:
        return "Bird authentication failed. Check BIRD_API_KEY."
    if status_code == 403:
        return "Bird rejected this API key or permission scope."
    if status_code == 422:
        guidance = "Bird rejected the email payload or sender."
        if "sender" in message or "domain" in message or "from" in message or "validation" in code:
            guidance += " Check that DEFAULT_FROM_EMAIL belongs to a verified Bird sending domain."
        else:
            guidance += " Check sender-domain verification and DEFAULT_FROM_EMAIL."
        return guidance
    if status_code == 429:
        return "Bird rate limit reached. Try again later."
    if status_code and status_code >= 500:
        return "Bird is temporarily unavailable."
    if "network" in code or "timeout" in message or "timed out" in message or "transient" in message:
        return "Bird request timed out."
    return "Email provider diagnostic failed."
