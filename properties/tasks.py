from datetime import timedelta
from celery import shared_task
from django.utils import timezone

from notifications.models import NotificationType
from notifications.services import notify_transactional
from .models import PropertyListingAddOn, PropertyListing
from .entitlements import lock_owner, consumes_slot, summary


def notify_unit(unit, event, message):
    p = unit.assigned_property
    recipients = {p.owner_id: p.owner}
    if p.agent_id and p.agent.is_active:
        recipients[p.agent.user_id] = p.agent.user
    if p.agency_id:
        for member in p.agency.agents.filter(is_active=True, role__in=["OWNER", "ADMIN"]).select_related("user"):
            recipients[member.user_id] = member.user
    for user in recipients.values():
        notify_transactional(
            user,
            NotificationType.LISTING_STATUS_UPDATE,
            "Property extra listing allowance",
            message,
            {
                "route": "/account/manage/properties" + (f"?agency={p.agency_id}" if p.agency_id else ""),
                "property_id": str(p.pk),
            },
            f"property-addon:{unit.pk}:{event}:{user.pk}",
            "listing_reminders_email",
        )


@shared_task
def process_property_entitlements():
    """Idempotent hourly expiry. Only the specific expiring extra property can pause."""
    now = timezone.now()
    processed = 0
    ids = PropertyListingAddOn.objects.exclude(status="UNUSED").values_list("pk", "account_id", "agency_id")
    for pk, account_id, agency_id in ids.iterator():
        with lock_owner(account_id, agency_id):
            unit = PropertyListingAddOn.objects.select_related(
                "assigned_property__owner", "assigned_property__agent__user"
            ).get(pk=pk)
            if unit.expires_at <= now:
                if unit.status == "ACTIVE":
                    unit.status = "EXPIRED"
                    unit.save()
                    listing = PropertyListing.objects.get(pk=unit.assigned_property_id)
                    if consumes_slot(listing) and summary(account_id, agency_id, now)["legacy_over_limit"]:
                        listing.status = "PAUSED"
                        listing.save(update_fields=["status", "updated_at"])
                    processed += 1
                # Repeat delivery attempts with the existing stable event key.
                notify_unit(
                    unit,
                    "expired",
                    f"The extra allowance for {unit.assigned_property.title} expired. The listing can remain live if ordinary plan capacity is available; otherwise it is paused. Your content is preserved. Contact an administrator to renew, then submit a paused listing for review.",
                )
            elif unit.status == "ACTIVE":
                remaining = unit.expires_at - now
                for days in (7, 1):
                    if remaining <= timedelta(days=days):
                        notify_unit(
                            unit,
                            f"reminder-{days}",
                            f"The extra allowance for {unit.assigned_property.title} expires on {unit.expires_at.date()}. Contact an administrator to renew. Extra allowances do not renew automatically.",
                        )
    return processed
