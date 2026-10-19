"""HTTPS-only external business social profile validators.

These fields are *outbound links*, never URLs that our servers fetch.
"""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


_ALLOWED = {
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com"},
    "instagram": {"instagram.com", "www.instagram.com"},
    "tiktok": {"tiktok.com", "www.tiktok.com"},
}


def _validate(value, platform):
    if not value:
        return
    if value.strip() != value or any(ord(ch) < 32 for ch in value):
        raise ValidationError("Enter a valid public HTTPS profile URL.", code="invalid_social_url")
    try:
        parsed = urlsplit(value)
        URLValidator(schemes=["https"])(value)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname not in _ALLOWED[platform]
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            raise ValueError("URL is not a supported social profile")
    except (ValueError, ValidationError):
        raise ValidationError(
            f"Enter a valid HTTPS {platform.title()} link using its official domain.",
            code="invalid_social_url",
        )


def validate_facebook_url(value):
    _validate(value, "facebook")


def validate_instagram_url(value):
    _validate(value, "instagram")


def validate_tiktok_url(value):
    _validate(value, "tiktok")
