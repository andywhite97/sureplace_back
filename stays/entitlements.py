"""Stay capacity counts establishments, never room inventory or booking availability."""

import copy
import uuid
from contextlib import contextmanager, ExitStack
from datetime import timedelta
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from core.entitlement_utils import lock_owner, package_unit_amounts
from .entitlement_models import StayPlan, StaySubscription, StayListingAddOn, StayCapacityReview


class StayListingLimitReached(APIException):
    status_code = 400
    default_code = "STAY_LISTING_LIMIT_REACHED"

    def __init__(self, usage):
        self.detail = {
            "code": self.default_code,
            "message": f"You have reached your {usage['listing_limit']} active stay listing limit. Your draft is saved; existing bookings are preserved.",
            "active_stays": usage["active_stay_count"],
            "listing_limit": usage["listing_limit"],
            "remaining_capacity": usage["remaining_publication_capacity"],
            "upgrade_available": True,
        }


def owner_filter(account_id=None, agency_id=None):
    return {"account_id": None, "agency_id": agency_id} if agency_id else {"account_id": account_id, "agency_id": None}


def stay_filter(account_id=None, agency_id=None):
    return {"agency_id": agency_id} if agency_id else {"owner_id": account_id, "agency_id": None}


def entitlement_owner(stay):
    return (None, stay.agency_id) if stay.agency_id else (stay.owner_id, None)


def consumes_slot(stay):
    from .models import StayStatus

    return stay.status == StayStatus.PUBLISHED


def active_stays(account_id=None, agency_id=None):
    from .models import Stay, StayStatus

    return Stay.objects.filter(**stay_filter(account_id, agency_id), status=StayStatus.PUBLISHED)


@contextmanager
def lock_stay_owners(stay, update_fields=None):
    from .models import Stay

    before = Stay.objects.filter(pk=stay.pk).first()
    effective = stay
    if before and update_fields is not None:
        effective = copy.copy(before)
        for field in update_fields:
            setattr(effective, field, getattr(stay, field))
    scopes = {entitlement_owner(effective)}
    if before:
        scopes.add(entitlement_owner(before))
    with transaction.atomic(), ExitStack() as stack:
        for account_id, agency_id in sorted(
            scopes, key=lambda pair: ("agency" if pair[1] else "account", str(pair[1] or pair[0]))
        ):
            stack.enter_context(lock_owner(account_id, agency_id))
        current = Stay.objects.select_for_update(of=("self",)).filter(pk=stay.pk).first()
        if before and current and (before.owner_id, before.agency_id) != (current.owner_id, current.agency_id):
            raise ValidationError("Stay ownership changed. Reload and try again.")
        yield current, effective


def effective_plan(account_id=None, agency_id=None, now=None):
    now = now or timezone.now()
    sub = (
        StaySubscription.objects.filter(**owner_filter(account_id, agency_id), starts_at__lte=now)
        .select_related("plan")
        .order_by("-starts_at", "-granted_at")
        .first()
    )
    if sub and sub.status in {"ACTIVE", "GRACE"} and now < sub.grace_until:
        return sub.plan, sub, "GRACE" if now >= sub.expires_at else "ACTIVE"
    return (
        StayPlan.objects.get(pk="HOST_FREE"),
        sub,
        ("CANCELLED" if sub and sub.status == "CANCELLED" else "EXPIRED" if sub else "FREE"),
    )


def booking_obligations(stay, now=None):
    from bookings.models import BookingStatus

    now = now or timezone.now()
    return stay.bookings.filter(
        status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED], check_out__gte=timezone.localdate(now)
    ).exclude(status=BookingStatus.PENDING, expires_at__lte=now)


def summary(account_id=None, agency_id=None, now=None, stay_id=None):
    from .models import Stay

    now = now or timezone.now()
    plan, sub, state = effective_plan(account_id, agency_id, now)
    units = StayListingAddOn.objects.filter(**owner_filter(account_id, agency_id))
    valid = units.filter(status="ACTIVE", expires_at__gt=now)
    unused = units.filter(status="UNUSED").filter(Q(activate_before__isnull=True) | Q(activate_before__gt=now)).count()
    live = active_stays(account_id, agency_id)
    count = live.count()
    bound = live.filter(pk__in=valid.values("assigned_stay_id")).count()
    ordinary = count - bound
    remaining = max(0, plan.active_listing_limit - ordinary) + (unused if ordinary <= plan.active_listing_limit else 0)
    # A correlated predicate avoids excluding a confirmed booking because an
    # unrelated expired pending booking happens to belong to the same stay.
    from django.db.models import Exists, OuterRef
    from bookings.models import Booking

    obligations = Booking.objects.filter(
        stay_id=OuterRef("pk"), status__in=["PENDING", "CONFIRMED"], check_out__gte=timezone.localdate(now)
    ).exclude(status="PENDING", expires_at__lte=now)
    protected = (
        ordinary > plan.active_listing_limit
        and live.annotate(has_obligations=Exists(obligations)).filter(has_obligations=True).exists()
    )
    reviews = StayCapacityReview.objects.filter(
        stay_id__in=Stay.objects.filter(**stay_filter(account_id, agency_id)).values("pk")
    )
    return {
        "account_type": "AGENCY" if agency_id else "INDIVIDUAL",
        "agency_id": str(agency_id) if agency_id else None,
        "current_plan": {
            "code": plan.code,
            "display_name": plan.display_name,
            "price": str(plan.price),
            "billing_interval": plan.billing_interval,
        },
        "subscription_status": state,
        "active_stay_count": count,
        "base_listing_allowance": plan.active_listing_limit,
        "active_extra_allowances": valid.count(),
        "unused_extra_allowances": unused,
        "base_slots_remaining": max(0, plan.active_listing_limit - ordinary),
        "remaining_publication_capacity": remaining,
        "listing_limit": plan.active_listing_limit + bound,
        "usage_percent": min(100, round(count * 100 / max(1, plan.active_listing_limit + bound))),
        "legacy_over_limit": ordinary > plan.active_listing_limit,
        "protected_booking_over_limit": protected,
        "can_publish_stay": remaining > 0 or (bool(stay_id) and valid.filter(assigned_stay_id=stay_id).exists()),
        "subscription_expiration": sub.expires_at if sub else None,
        "subscription_grace_until": sub.grace_until if sub else None,
        "grace_entered_at": sub.grace_entered_at if sub else None,
        "activated_addons": list(
            units.exclude(status="UNUSED").values(
                "id", "assigned_stay_id", "activated_at", "expires_at", "status", "expiry_processed_at"
            )
        ),
        "capacity_reviews": list(
            reviews.values(
                "stay_id", "status", "reason", "pause_when_safe", "opened_at", "resolved_at", stay_name=F("stay__name")
            )
        ),
        "checkout_available": False,
    }


def available_unit(account_id=None, agency_id=None, now=None):
    now = now or timezone.now()
    return (
        StayListingAddOn.objects.filter(**owner_filter(account_id, agency_id), status="UNUSED")
        .filter(Q(activate_before__isnull=True) | Q(activate_before__gt=now))
        .order_by("granted_at", "unit_number", "id")
        .first()
    )


def ensure_capacity(stay):
    now = timezone.now()
    units = StayListingAddOn.objects.filter(**owner_filter(stay.owner_id, stay.agency_id))
    if units.filter(assigned_stay=stay.pk, status="ACTIVE", expires_at__gt=now).exists():
        return None
    usage = summary(stay.owner_id, stay.agency_id, now, stay.pk)
    if usage["legacy_over_limit"]:
        raise StayListingLimitReached(usage)
    if usage["base_slots_remaining"]:
        return None
    unit = available_unit(stay.owner_id, stay.agency_id, now)
    if unit:
        return unit
    raise StayListingLimitReached(usage)


def activate_unit(unit, stay):
    now = timezone.now()
    for previous in StayListingAddOn.objects.filter(assigned_stay=stay, status="ACTIVE", expires_at__lte=now):
        previous.status = "EXPIRED"
        previous.expiry_processed_at = now
        previous.save()
    unit.assigned_stay = stay
    unit.status = "ACTIVE"
    unit.activated_at = now
    unit.expires_at = now + timedelta(days=unit.duration_days)
    unit.save()
    review = StayCapacityReview.objects.filter(stay=stay).exclude(status="RESOLVED").first()
    if review:
        set_review(stay, review.reason, "RESOLVED", pause_when_safe=review.pause_when_safe, addon=review.expired_addon)


def check_submission(stay):
    with lock_owner(stay.owner_id, stay.agency_id):
        ensure_capacity(stay)


def set_review(stay, reason, status, *, pause_when_safe=False, addon=None):
    from moderation.models import ModerationAuditEvent

    review = StayCapacityReview.objects.filter(stay=stay).first()
    changed = not review or (review.reason, review.status, review.expired_addon_id) != (
        reason,
        status,
        addon.pk if addon else None,
    )
    if not review:
        review = StayCapacityReview(stay=stay, reason=reason, status=status)
    if review.status == "RESOLVED" and status != "RESOLVED":
        review.opened_at = timezone.now()
    review.reason = reason
    review.status = status
    review.pause_when_safe = pause_when_safe
    review.expired_addon = addon
    review.last_checked_at = timezone.now()
    review.resolved_at = (review.resolved_at or timezone.now()) if status == "RESOLVED" else None
    review.full_clean()
    review.save()
    if changed:
        ModerationAuditEvent.objects.create(
            stay=stay,
            action="STAY_CAPACITY_REVIEW",
            reason=reason,
            metadata={
                "status": status,
                "addon_id": str(addon.pk) if addon else None,
                "pause_when_safe": pause_when_safe,
            },
        )
    return review


def require_grant_permission(actor, model_name):
    if not actor.is_active or not actor.is_staff or not actor.has_perm(f"stays.add_{model_name}"):
        raise PermissionDenied("Staff grant permission is required.")


def grant_package(
    package, *, actor, reason, account=None, agency=None, reference=None, provider="", transaction_reference=""
):
    require_grant_permission(actor, "staylistingaddon")
    if not reason.strip() or bool(account) == bool(agency) or not package.is_active:
        raise ValidationError("A reason, exactly one owner and an active package are required.")
    reference = reference or uuid.uuid4()
    with lock_owner(account.pk if account else None, agency.pk if agency else None):
        existing = StayListingAddOn.objects.filter(purchase_reference=reference)
        if existing.exists():
            if (
                existing.exclude(
                    **owner_filter(account.pk if account else None, agency.pk if agency else None)
                ).exists()
                or existing.exclude(source_package=package).exists()
            ):
                raise ValidationError("Purchase reference belongs to another owner or package.")
            return list(existing)
        amounts = package_unit_amounts(package.price, package.quantity)
        return [
            StayListingAddOn.objects.create(
                account=account,
                agency=agency,
                source_package=package,
                granted_by=actor,
                grant_reason=reason,
                provider=provider,
                transaction_reference=transaction_reference,
                purchase_reference=reference,
                unit_number=index + 1,
                amount=amounts[index],
                duration_days=package.duration_days,
                activate_before=(
                    timezone.now() + timedelta(days=package.purchase_validity_days)
                    if package.purchase_validity_days
                    else None
                ),
            )
            for index in range(package.quantity)
        ]


def allocate_renewal(stay, *, actor):
    if not actor.is_active or not actor.is_staff or not actor.has_perm("stays.change_staylistingaddon"):
        raise PermissionDenied("Staff entitlement allocation permission is required.")
    with lock_stay_owners(stay) as (current, _):
        now = timezone.now()
        existing = StayListingAddOn.objects.filter(
            **owner_filter(current.owner_id, current.agency_id),
            assigned_stay=current,
            status="ACTIVE",
            expires_at__gt=now,
        ).first()
        if existing:
            return existing
        unit = available_unit(current.owner_id, current.agency_id, now)
        if not unit:
            raise ValidationError("Grant an extra stay package to this owner before allocating renewal.")
        activate_unit(unit, current)
        from moderation.models import ModerationAuditEvent

        ModerationAuditEvent.objects.create(
            actor=actor,
            stay=current,
            action="STAY_ALLOWANCE_RENEWED",
            reason=unit.grant_reason,
            metadata={"addon_id": str(unit.pk)},
        )
        return unit
