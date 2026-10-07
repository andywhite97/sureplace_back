from datetime import timedelta
import random

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.functions import Coalesce
from django.utils import timezone
from alerts.models import Frequency, SavedSearch
from alerts.services import evaluate
from bookings.services import expire_pending
from properties.models import AvailabilityStatus, ListingStatus, PropertyListing
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
    now = timezone.now()
    reminder_cutoff = now - timedelta(days=settings.PROPERTY_AVAILABILITY_REMINDER_DAYS)
    expiry_cutoff = now - timedelta(days=settings.PROPERTY_AVAILABILITY_STALE_DAYS)
    count = 0
    due = PropertyListing.objects.filter(
        status=ListingStatus.PUBLISHED, availability_status=AvailabilityStatus.AVAILABLE,
    ).annotate(last_confirmation=Coalesce("availability_confirmed_at", "published_at", "created_at"))
    for listing_id in due.filter(last_confirmation__lte=reminder_cutoff).values_list("id", flat=True):
        with transaction.atomic():
            p = due.select_for_update(of=("self",)).select_related("owner", "agent__user").filter(id=listing_id).first()
            if not p or p.last_confirmation > reminder_cutoff:
                continue
            expired = p.last_confirmation <= expiry_cutoff
            if not expired and p.availability_reminded_at:
                continue
            if expired:
                p.availability_status = AvailabilityStatus.UNAVAILABLE
                p.save(update_fields=["availability_status", "updated_at"])
                transaction.on_commit(lambda: cache.delete("properties:featured:v2"), robust=True)
            else:
                p.availability_reminded_at = now
                p.save(update_fields=["availability_reminded_at"])
            recipients = {p.owner_id: p.owner}
            if p.agent and p.agent.is_active:
                recipients[p.agent.user_id] = p.agent.user
            for user in recipients.values():
                notify_transactional(
                    user,
                    NotificationType.LISTING_STATUS_UPDATE if expired else NotificationType.LISTING_AVAILABILITY_REMINDER,
                    "Property marked unavailable" if expired else "Is your property still available?",
                    f"{p.title} was marked unavailable because availability was not confirmed within {settings.PROPERTY_AVAILABILITY_STALE_DAYS} days. Confirm availability to show it again."
                    if expired else f"Please confirm whether {p.title} is still available. Without confirmation it will be marked unavailable {settings.PROPERTY_AVAILABILITY_STALE_DAYS} days after the last confirmation.",
                    {"route": "/account/manage/properties" + (f"?agency={p.agency_id}" if p.agency_id else ""), "property_id": str(p.id), "action_label": "Manage availability"},
                    f"availability:{p.id}:{p.last_confirmation.isoformat()}:{'expired' if expired else 'reminder'}",
                    "listing_reminders_email",
                )
            count += 1
    return count


@shared_task(bind=True, max_retries=4)
def send_email_delivery_task(
    self, delivery_id, to, subject, text, html, template_key="transactional", tags=None, metadata=None
):
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
