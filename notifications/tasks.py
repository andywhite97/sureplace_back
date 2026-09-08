from datetime import timedelta
import random

from celery import shared_task
from django.utils import timezone
from alerts.models import Frequency, SavedSearch
from alerts.services import evaluate
from bookings.services import expire_pending
from properties.models import ListingStatus, PropertyListing
from .email_providers import PermanentEmailProviderError, RetryableEmailProviderError
from .models import NotificationType
from .services import notify_transactional, send_email_delivery


@shared_task
def expire_bookings_task():
    return expire_pending()


@shared_task
def evaluate_saved_searches():
    now = timezone.now()
    count = 0
    for s in SavedSearch.objects.filter(notifications_enabled=True).exclude(frequency=Frequency.OFF):
        due = (
            not s.last_checked_at
            or s.frequency == Frequency.INSTANT
            or s.last_checked_at <= now - timedelta(days=1 if s.frequency == Frequency.DAILY else 7)
        )
        if due:
            found = evaluate(s)
            if found:
                notify_transactional(
                    s.user,
                    NotificationType.SAVED_SEARCH_MATCH,
                    f"New matches for {s.name}",
                    f"{len(found)} new matches.",
                    {"route": f"/saved-searches/{s.id}", "saved_search_id": str(s.id), "match_count": len(found)},
                    f"search:{s.id}:{now.date()}",
                    "saved_search_email",
                )
                s.last_notified_at = now
                s.save()
                count += len(found)
    return count


@shared_task
def property_availability_reminders():
    cutoff = timezone.now() - timedelta(days=30)
    count = 0
    for p in PropertyListing.objects.filter(status=ListingStatus.PUBLISHED, availability_confirmed_at__lt=cutoff):
        notify_transactional(
            p.owner,
            NotificationType.LISTING_AVAILABILITY_REMINDER,
            "Confirm availability",
            f"Please confirm {p.title}.",
            {"route": f"/properties/{p.slug}", "property_id": str(p.id)},
            f"availability:{p.id}:{timezone.now().date()}",
            "listing_reminders_email",
        )
        count += 1
    return count


@shared_task(bind=True, max_retries=4)
def send_email_delivery_task(self, delivery_id, to, subject, text, html, template_key="transactional", tags=None, metadata=None):
    try:
        result = send_email_delivery(
            delivery_id,
            to,
            subject,
            text,
            html,
            template_key=template_key,
            tags=tags or {},
            metadata=metadata or {},
        )
    except RetryableEmailProviderError as exc:
        delay = min(300, (2**self.request.retries) * 30 + random.randint(0, 10))
        raise self.retry(exc=exc, countdown=delay)
    except PermanentEmailProviderError:
        return {"status": "failed", "delivery_id": delivery_id}
    return {
        "status": result.status,
        "provider": result.provider,
        "provider_message_id": result.provider_message_id,
        "delivery_id": delivery_id,
    }
