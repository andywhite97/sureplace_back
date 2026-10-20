"""Public business destinations. Validation never fetches submitted URLs."""

import ipaddress
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def public_https(value, domain=None):
    if not value:
        return value
    try:
        URLValidator(schemes=["https"])(value)
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if url.username or url.password or url.port not in (None, 443) or "\\" in value:
            raise ValueError()
        if any(ord(c) < 33 for c in value) or "%" in host:
            raise ValueError()
        if domain:
            if host not in (domain, "www." + domain, "m." + domain):
                raise ValueError()
            if not url.path.strip("/") or url.path.lower().startswith(("/l.php", "/redirect", "/share", "/login")):
                raise ValueError()
        else:
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host or host.endswith(
                    (".local", ".localhost", ".internal", ".test", ".invalid", ".example", ".home", ".lan")
                ):
                    raise ValueError()
                if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
                    raise ValueError()
                if not re.search(r"\.[a-z]{2,}$", host):
                    raise ValueError()
            else:
                if not address.is_global:
                    raise ValueError()
    except (ValueError, ValidationError):
        raise ValidationError("Enter a public HTTPS business URL" + (f" on {domain}." if domain else "."))
    return value


def facebook_url(value):
    return public_https(value, "facebook.com")


def instagram_url(value):
    return public_https(value, "instagram.com")


def tiktok_url(value):
    return public_https(value, "tiktok.com")


def whatsapp_number(value):
    if value and not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        raise ValidationError("Use + and the international country code, followed by 8–15 digits.")
    return value


class SocialValidationMixin:
    def validate_whatsapp_number(self, value):
        value = re.sub(r"[ ()-]", "", value)
        try:
            return whatsapp_number(value)
        except ValidationError as error:
            from rest_framework.exceptions import ValidationError as APIValidationError

            raise APIValidationError(error.messages)
