from django.conf import settings
import logging
from django.utils.html import escape
from django.utils import timezone

from .email_providers import EmailProviderError, build_email_message, get_email_provider
from .models import EmailDelivery, Notification, NotificationPreference

logger = logging.getLogger(__name__)

ALLOWED = {
    "route",
    "conversation_id",
    "property_id",
    "property_slug",
    "stay_id",
    "viewing_id",
    "booking_id",
    "saved_search_id",
    "match_count",
}


def create_notification(user, kind, title, message, data=None, event_key=None):
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    if not pref.in_app_enabled:
        return None
    safe = {k: v for k, v in (data or {}).items() if k in ALLOWED}
    return Notification.objects.get_or_create(
        user=user,
        event_key=event_key,
        defaults={"notification_type": kind, "title": title, "message": message, "data": safe},
    )[0]


def render_transactional_email(message, route=""):
    url = settings.FRONTEND_BASE_URL.rstrip("/") + "/" + route.lstrip("/") if route else settings.FRONTEND_BASE_URL
    html = f"<div><h2>SurePlace</h2><p>{escape(message)}</p><a href='{escape(url)}'>View on SurePlace</a></div>"
    return message, html


def send_transactional_email(
    to,
    subject,
    message,
    route="",
    *,
    notification=None,
    template_key="transactional",
    tags=None,
    metadata=None,
):
    text, html = render_transactional_email(message, route)
    delivery = EmailDelivery.objects.create(
        notification=notification,
        recipient=to,
        subject=subject,
        provider=getattr(settings, "EMAIL_PROVIDER", "django"),
        template_key=template_key,
    )
    return send_email_delivery(delivery.id, to, subject, text, html, template_key=template_key, tags=tags, metadata=metadata)


def enqueue_transactional_email(
    to,
    subject,
    message,
    route="",
    *,
    notification=None,
    template_key="transactional",
    tags=None,
    metadata=None,
):
    text, html = render_transactional_email(message, route)
    delivery = EmailDelivery.objects.create(
        notification=notification,
        recipient=to,
        subject=subject,
        provider=getattr(settings, "EMAIL_PROVIDER", "django"),
        template_key=template_key,
    )
    from .tasks import send_email_delivery_task

    send_email_delivery_task.delay(str(delivery.id), to, subject, text, html, template_key, tags or {}, metadata or {})
    return delivery


def send_email_delivery(delivery_id, to, subject, text, html, *, template_key="transactional", tags=None, metadata=None):
    delivery = EmailDelivery.objects.get(id=delivery_id)
    message = build_email_message(
        to,
        subject,
        text,
        html,
        template_key=template_key,
        tags=tags or {},
        metadata={**(metadata or {}), "email_delivery_id": str(delivery.id)},
        idempotency_key=str(delivery.id),
    )
    delivery.attempts += 1
    delivery.provider = getattr(settings, "EMAIL_PROVIDER", "django")
    delivery.save(update_fields=["attempts", "provider"])
    try:
        result = get_email_provider().send(message)
    except EmailProviderError as exc:
        delivery.last_error_code = exc.code
        delivery.last_error_message = exc.safe_message
        delivery.failed_at = timezone.now()
        delivery.status = EmailDelivery.Status.FAILED
        delivery.save(update_fields=["last_error_code", "last_error_message", "failed_at", "status"])
        logger.warning(
            "email_delivery_failed provider=%s template_key=%s delivery_id=%s recipient=%s status_code=%s code=%s",
            delivery.provider,
            delivery.template_key,
            delivery.id,
            mask_email(delivery.recipient),
            exc.status_code,
            exc.code,
        )
        raise
    delivery.provider = result.provider
    delivery.provider_message_id = result.provider_message_id
    delivery.status = EmailDelivery.Status.ACCEPTED
    delivery.accepted_at = timezone.now()
    delivery.last_error_code = ""
    delivery.last_error_message = ""
    delivery.save(
        update_fields=[
            "provider",
            "provider_message_id",
            "status",
            "accepted_at",
            "last_error_code",
            "last_error_message",
        ]
    )
    logger.info(
        "email_delivery_accepted provider=%s provider_message_id=%s template_key=%s delivery_id=%s recipient=%s",
        result.provider,
        result.provider_message_id,
        delivery.template_key,
        delivery.id,
        mask_email(delivery.recipient),
    )
    return result


def notify_transactional(user, kind, title, message, data, event_key, email_flag):
    from django.db import transaction

    def deliver():
        notification = create_notification(user, kind, title, message, data, event_key)
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        if notification and pref.email_enabled and getattr(pref, email_flag, False):
            email_category = kind.lower()
            enqueue_transactional_email(
                user.email,
                title,
                message,
                data.get("route", ""),
                notification=notification,
                template_key=email_category,
                tags={"category": email_category},
                metadata={"notification_id": str(notification.id)},
            )

    transaction.on_commit(deliver)


def mask_email(value):
    local, separator, domain = value.partition("@")
    if not separator:
        return "***"
    return f"{local[:1]}***@{domain}"
