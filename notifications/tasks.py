from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from alerts.models import Frequency, SavedSearch
from alerts.services import evaluate
from bookings.services import expire_pending
from properties.models import ListingStatus, PropertyListing
from .models import NotificationType
from .services import create_notification


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
                create_notification(
                    s.user,
                    NotificationType.SAVED_SEARCH_MATCH,
                    f"New matches for {s.name}",
                    f"{len(found)} new matches.",
                    {"route": f"/saved-searches/{s.id}", "saved_search_id": str(s.id), "match_count": len(found)},
                    f"search:{s.id}:{now.date()}",
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
        create_notification(
            p.owner,
            NotificationType.LISTING_AVAILABILITY_REMINDER,
            "Confirm availability",
            f"Please confirm {p.title}.",
            {"route": f"/properties/{p.slug}", "property_id": str(p.id)},
            f"availability:{p.id}:{timezone.now().date()}",
        )
        count += 1
    return count
