from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape
from .models import Notification, NotificationPreference

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


def send_transactional_email(to, subject, message, route=""):
    url = settings.FRONTEND_BASE_URL.rstrip("/") + "/" + route.lstrip("/") if route else settings.FRONTEND_BASE_URL
    mail = EmailMultiAlternatives(subject, message, settings.DEFAULT_FROM_EMAIL, [to])
    mail.attach_alternative(
        f"<div><h2>SurePlace</h2><p>{escape(message)}</p><a href='{escape(url)}'>View on SurePlace</a></div>",
        "text/html",
    )
    return mail.send()


def notify_transactional(user, kind, title, message, data, event_key, email_flag):
    from django.db import transaction

    def deliver():
        notification = create_notification(user, kind, title, message, data, event_key)
        pref, _ = NotificationPreference.objects.get_or_create(user=user)
        if notification and pref.email_enabled and getattr(pref, email_flag, False):
            send_transactional_email(user.email, title, message, data.get("route", ""))

    transaction.on_commit(deliver)
