from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from notifications.models import NotificationType
from notifications.services import notify_transactional
from .models import Stay, RoomType, StaySubscription, StayListingAddOn, StayCapacityReview
from .entitlements import lock_owner, consumes_slot, summary, booking_obligations, set_review


def notify_scope(account_id, agency_id, event, message, stay=None):
    from accounts.models import User
    from agencies.models import AgentProfile

    recipients = {}
    if account_id:
        recipients[account_id] = User.objects.get(pk=account_id)
    if agency_id:
        for member in AgentProfile.objects.filter(
            agency_id=agency_id, is_active=True, role__in=["OWNER", "ADMIN"]
        ).select_related("user"):
            recipients[member.user_id] = member.user
    if stay:
        recipients[stay.owner_id] = stay.owner
        if stay.agent_id and stay.agent.is_active:
            recipients[stay.agent.user_id] = stay.agent.user
    for recipient in recipients.values():
        notify_transactional(
            recipient,
            NotificationType.LISTING_STATUS_UPDATE,
            "Stay listing allowance",
            message,
            {
                "route": "/account/manage/stays" + (f"?agency={agency_id}" if agency_id else ""),
                **({"stay_id": str(stay.pk)} if stay else {}),
            },
            f"stay-entitlement:{event}:{recipient.pk}",
            "listing_reminders_email",
        )


def resolve_expired_stay(unit, now):
    """Owner -> rooms -> stay. Bookings take room -> stay, never the owner lock.

    No Booking, RoomType or RoomAvailability row is written by this operation.
    Pending holds and confirmed/current reservations prevent automated pausing.
    """
    if StayListingAddOn.objects.filter(
        assigned_stay_id=unit.assigned_stay_id, activated_at__gt=unit.activated_at
    ).exists():
        return "renewed"
    list(RoomType.objects.select_for_update(of=("self",)).filter(stay_id=unit.assigned_stay_id).order_by("pk"))
    stay = Stay.objects.select_for_update(of=("self",)).get(pk=unit.assigned_stay_id)
    usage = summary(unit.account_id, unit.agency_id, now)
    other_valid = stay.listing_addons.filter(status="ACTIVE", expires_at__gt=now).exists()
    if not consumes_slot(stay) or other_valid or not usage["legacy_over_limit"]:
        if StayCapacityReview.objects.filter(stay=stay).exclude(status="RESOLVED").exists():
            set_review(stay, "ADDON_EXPIRED", "RESOLVED", pause_when_safe=True, addon=unit)
        return "covered"
    if booking_obligations(stay, now).exists():
        review = set_review(stay, "ADDON_EXPIRED", "PROTECTED_BOOKINGS", pause_when_safe=True, addon=unit)
        notify_scope(
            unit.account_id,
            unit.agency_id,
            f"protected:{unit.pk}:{review.opened_at.isoformat()}",
            f"{stay.name} is over its listing allowance and protected because it has pending or current/future confirmed reservations. It remains published and booking workflows continue. Renew its allowance or ask an administrator to review. No reservation, price or inventory has been changed.",
            stay,
        )
        return "protected"
    # After obligations finish, only an add-on-expiry listing is eligible for an
    # automatic pause. Legacy/subscription over-limit listings are preserved.
    stay.status = "PAUSED"
    stay.save(update_fields=["status", "updated_at"])
    set_review(stay, "ADDON_EXPIRED", "RESOLVED", pause_when_safe=True, addon=unit)
    notify_scope(
        unit.account_id,
        unit.agency_id,
        f"paused:{unit.pk}",
        f"{stay.name} was paused after its extra allowance expired and no outstanding booking obligations remained. Rooms, calendars, messages and all booking history are preserved. Arrange renewal and resubmit it for review.",
        stay,
    )
    return "paused"


def review_scope(account_id, agency_id, now, subscription=None):
    from .entitlements import active_stays

    usage = summary(account_id, agency_id, now)
    if not usage["legacy_over_limit"]:
        for review in StayCapacityReview.objects.filter(
            stay_id__in=active_stays(account_id, agency_id).values("pk")
        ).exclude(status="RESOLVED"):
            set_review(
                review.stay,
                review.reason,
                "RESOLVED",
                pause_when_safe=review.pause_when_safe,
                addon=review.expired_addon,
            )
        return
    reason = "SUBSCRIPTION_EXPIRED" if subscription else "LEGACY_OVER_LIMIT"
    event = f"over-limit:{agency_id or account_id}:{subscription.pk if subscription else 'legacy'}:{subscription.expires_at.isoformat() if subscription else 'free'}"
    # Do not mass-pause pre-existing subscription or legacy inventory.
    for stay in active_stays(account_id, agency_id):
        existing = (
            StayCapacityReview.objects.filter(stay=stay, reason="ADDON_EXPIRED").exclude(status="RESOLVED").first()
        )
        if existing:
            continue
        if stay.listing_addons.filter(status="ACTIVE", expires_at__gt=now).exists():
            continue
        state = "PROTECTED_BOOKINGS" if booking_obligations(stay, now).exists() else "OVER_LIMIT"
        set_review(stay, reason, state)
        if state == "PROTECTED_BOOKINGS":
            notify_scope(
                account_id,
                agency_id,
                f"{event}:protected:{stay.pk}",
                f"{stay.name} is protected while existing booking obligations remain. Please renew or ask an administrator to review your over-limit stay allowance. Booking workflows remain available.",
                stay,
            )
    notify_scope(
        account_id,
        agency_id,
        event,
        "Your stay account is over its active listing allowance. Existing published stays and reservations are preserved. Additional stay publication is restricted until capacity is restored. Compare hosting plans or contact an administrator.",
    )


@shared_task
def process_stay_entitlements():
    now = timezone.now()
    processed = 0
    scopes = set()
    for pk, account_id, agency_id in StaySubscription.objects.values_list("pk", "account_id", "agency_id").iterator():
        scopes.add((account_id, agency_id))
        with lock_owner(account_id, agency_id):
            sub = StaySubscription.objects.get(pk=pk)
            if sub.status in {"ACTIVE", "GRACE"} and sub.expires_at <= now:
                if now < sub.grace_until:
                    if sub.status != "GRACE":
                        sub.status = "GRACE"
                        sub.grace_entered_at = now
                        sub.save()
                    notify_scope(
                        account_id,
                        agency_id,
                        f"subscription:{sub.pk}:grace:{sub.expires_at.isoformat()}",
                        f"Your {sub.plan.display_name} stay subscription has entered grace until {sub.grace_until.date()}. Paid base capacity and all reservations remain available. Arrange renewal with an administrator.",
                    )
                else:
                    sub.status = "EXPIRED"
                    sub.expired_at = now
                    sub.save()
    for pk, account_id, agency_id in (
        StayListingAddOn.objects.exclude(status="UNUSED").values_list("pk", "account_id", "agency_id").iterator()
    ):
        scopes.add((account_id, agency_id))
        with lock_owner(account_id, agency_id):
            unit = StayListingAddOn.objects.get(pk=pk)
            if unit.expires_at <= now:
                if unit.status == "ACTIVE":
                    unit.status = "EXPIRED"
                    unit.expiry_processed_at = now
                    unit.save()
                    processed += 1
                outcome = resolve_expired_stay(unit, now)
                notify_scope(
                    account_id,
                    agency_id,
                    f"addon:{unit.pk}:expired",
                    f"The extra allowance for {unit.assigned_stay.name} expired. State: {outcome}. Existing reservations, price snapshots, room inventory and history are preserved. Extra stay allowances do not renew automatically.",
                    unit.assigned_stay,
                )
            elif unit.status == "ACTIVE":
                for days in (7, 1):
                    if unit.expires_at - now <= timedelta(days=days):
                        notify_scope(
                            account_id,
                            agency_id,
                            f"addon:{unit.pk}:reminder-{days}",
                            f"The extra allowance for {unit.assigned_stay.name} expires on {unit.expires_at.date()}. Arrange renewal with an administrator. Existing reservations are protected.",
                            unit.assigned_stay,
                        )
    # Include grandfathered hosts with no subscription/extra ledger at all.
    for owner_id, agency_id in Stay.objects.filter(status="PUBLISHED").values_list("owner_id", "agency_id").distinct():
        scopes.add((None if agency_id else owner_id, agency_id))
    for account_id, agency_id in sorted(scopes, key=lambda scope: str(scope[1] or scope[0])):
        with lock_owner(account_id, agency_id):
            _, sub, _ = __import__("stays.entitlements", fromlist=["effective_plan"]).effective_plan(
                account_id, agency_id, now
            )
            review_scope(account_id, agency_id, now, sub)
    return processed
