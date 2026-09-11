import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from notifications.services import enqueue_transactional_email

logger = logging.getLogger(__name__)

PURPOSE = "email_verification"
SALT = "sureplace.accounts.email_verification"


class EmailVerificationError(Exception):
    code = "invalid"


class EmailVerificationExpired(EmailVerificationError):
    code = "expired"


def ttl_seconds() -> int:
    return int(getattr(settings, "EMAIL_VERIFICATION_TTL_SECONDS", 86400))


def make_email_verification_token(user) -> str:
    return signing.dumps({"purpose": PURPOSE, "user_id": str(user.pk), "email": user.email}, salt=SALT)


def verify_email_token(token: str):
    from django.contrib.auth import get_user_model

    try:
        payload = signing.loads(token, salt=SALT, max_age=ttl_seconds())
    except signing.SignatureExpired as exc:
        raise EmailVerificationExpired() from exc
    except signing.BadSignature as exc:
        raise EmailVerificationError() from exc
    if payload.get("purpose") != PURPOSE or not payload.get("user_id") or not payload.get("email"):
        raise EmailVerificationError()
    user = get_user_model().objects.filter(pk=payload["user_id"], is_active=True).first()
    if not user or user.email.lower() != str(payload["email"]).lower():
        raise EmailVerificationError()
    return user


def verification_route(token: str) -> str:
    return "verify-email?" + urlencode({"token": token})


def enqueue_verification_email(user):
    token = make_email_verification_token(user)
    route = verification_route(token)
    link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/{route}"
    expires_hours = max(1, ttl_seconds() // 3600)
    return enqueue_transactional_email(
        user.email,
        "Verify your SurePlace email",
        "Thanks for joining SurePlace. Confirm your email address to finish setting up your account.",
        route,
        template_key="auth.verify_email",
        tags={"category": "auth.verify_email"},
        metadata={"user_id": str(user.id), "purpose": PURPOSE},
        context={
            "cta_url": link,
            "expiry_text": f"This link expires in {expires_hours} hours.",
        },
    )


def enqueue_verification_email_after_commit(user):
    def deliver():
        try:
            enqueue_verification_email(user)
        except Exception:
            logger.exception("email_verification_enqueue_failed user_id=%s", user.id)

    transaction.on_commit(deliver)


def enqueue_welcome_email_once(user):
    if user.welcome_email_sent_at:
        return False
    user.welcome_email_sent_at = timezone.now()
    user.save(update_fields=["welcome_email_sent_at", "updated_at"])
    enqueue_transactional_email(
        user.email,
        "Welcome to SurePlace",
        (
            "Your account is ready. You can now explore properties, save favourites, "
            "request viewings, book stays, and message hosts or agents."
        ),
        "/properties",
        template_key="auth.welcome",
        tags={"category": "auth.welcome"},
        metadata={"user_id": str(user.id)},
    )
    return True
