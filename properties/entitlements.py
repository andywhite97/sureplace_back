"""Single source of capacity rules. Lock the existing owner row before any listing write."""

from contextlib import contextmanager, ExitStack
from datetime import timedelta
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from core.entitlement_utils import lock_owner, package_unit_amounts
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from .entitlement_models import PropertyPlan, PropertySubscription, PropertyListingAddOn


class PropertyListingLimitReached(APIException):
    status_code = 400
    default_code = "PROPERTY_LISTING_LIMIT_REACHED"

    def __init__(self, summary):
        # Keep JSON counts and booleans typed; APIException normally stringifies everything.
        self.detail = {
            "code": self.default_code,
            "message": f"You have reached your {summary['listing_limit']} active listing limit.",
            "active_listings": summary["active_listing_count"],
            "listing_limit": summary["listing_limit"],
            "upgrade_available": True,
        }


def owner_filter(account_id=None, agency_id=None):
    return {"agency_id": agency_id, "account_id": None} if agency_id else {"account_id": account_id, "agency_id": None}



@contextmanager
def lock_listing_owners(listing, update_fields=None):
    """Lock persisted and destination scopes in stable order for transfers/partial saves."""
    from .models import PropertyListing

    before = PropertyListing.objects.filter(pk=listing.pk).first()
    effective = listing
    if before and update_fields is not None:
        import copy

        effective = copy.copy(before)
        for field in update_fields:
            setattr(effective, field, getattr(listing, field))
    scopes = {(effective.owner_id if not effective.agency_id else None, effective.agency_id)}
    if before:
        scopes.add((before.owner_id if not before.agency_id else None, before.agency_id))
    with transaction.atomic(), ExitStack() as stack:
        for account_id, agency_id in sorted(
            scopes, key=lambda value: ("agency" if value[1] else "account", str(value[1] or value[0]))
        ):
            stack.enter_context(lock_owner(account_id, agency_id))
        current = PropertyListing.objects.select_for_update().filter(pk=listing.pk).first()
        if before and current and (before.owner_id, before.agency_id) != (current.owner_id, current.agency_id):
            raise ValidationError("Property ownership changed during this request. Reload and try again.")
        yield current


def active_listings(account_id=None, agency_id=None):
    from .models import PropertyListing

    scope = {"agency_id": agency_id} if agency_id else {"owner_id": account_id, "agency_id": None}
    return PropertyListing.objects.filter(**scope, status="PUBLISHED", availability_status="AVAILABLE")


def effective_plan(account_id=None, agency_id=None, now=None):
    now = now or timezone.now()
    sub = (
        PropertySubscription.objects.filter(**owner_filter(account_id, agency_id), status="ACTIVE", starts_at__lte=now)
        .select_related("plan")
        .first()
    )
    grace = timedelta(days=settings.PROPERTY_SUBSCRIPTION_GRACE_DAYS)
    if sub and now < sub.expires_at + grace:
        return sub.plan, sub, "GRACE" if now >= sub.expires_at else "ACTIVE"
    plan = PropertyPlan.objects.get(code="AGENCY_FREE" if agency_id else "INDIVIDUAL_FREE")
    return plan, sub, "EXPIRED" if sub else "FREE"


def summary(account_id=None, agency_id=None, now=None, property_id=None):
    now = now or timezone.now()
    plan, sub, state = effective_plan(account_id, agency_id, now)
    addons = PropertyListingAddOn.objects.filter(**owner_filter(account_id, agency_id))
    valid = addons.filter(status="ACTIVE", expires_at__gt=now)
    unused = addons.filter(status="UNUSED").filter(Q(activate_before__isnull=True) | Q(activate_before__gt=now)).count()
    live = active_listings(account_id, agency_id)
    count = live.count()
    bound_count = live.filter(pk__in=valid.values("assigned_property_id")).count()
    ordinary = count - bound_count
    return {
        "account_type": "AGENCY" if agency_id else "INDIVIDUAL",
        "agency_id": str(agency_id) if agency_id else None,
        "current_plan": {
            "code": plan.code,
            "display_name": plan.display_name,
            "price": str(plan.price),
            "billing_interval": plan.billing_interval,
        },
        "active_listing_count": count,
        "base_listing_allowance": plan.active_listing_limit,
        "active_extra_allowances": valid.count(),
        "unused_extra_allowances": unused,
        "listing_limit": plan.active_listing_limit + bound_count,
        "remaining_publication_capacity": max(0, plan.active_listing_limit - ordinary) + unused,
        "can_publish_property": ordinary < plan.active_listing_limit
        or unused > 0
        or (bool(property_id) and valid.filter(assigned_property_id=property_id).exists()),
        "base_slots_remaining": max(0, plan.active_listing_limit - ordinary),
        "usage_percent": min(100, round(count * 100 / max(1, plan.active_listing_limit + bound_count))),
        "legacy_over_limit": ordinary > plan.active_listing_limit,
        "subscription_status": state,
        "subscription_expiration": sub.expires_at if sub else None,
        "subscription_grace_until": (
            sub.expires_at + timedelta(days=settings.PROPERTY_SUBSCRIPTION_GRACE_DAYS) if sub else None
        ),
        "activated_addons": list(
            addons.exclude(status="UNUSED").values("id", "assigned_property_id", "activated_at", "expires_at", "status")
        ),
        "checkout_available": False,
    }


def consumes_slot(listing):
    return listing.status == "PUBLISHED" and listing.availability_status == "AVAILABLE"


def ensure_capacity(listing):
    """Caller holds owner lock. Return the server-granted unit needed for publication."""
    now = timezone.now()
    scope = owner_filter(listing.owner_id, listing.agency_id)
    addons = PropertyListingAddOn.objects.filter(**scope)
    if addons.filter(assigned_property_id=listing.pk, status="ACTIVE", expires_at__gt=now).exists():
        return None
    s = summary(listing.owner_id, listing.agency_id, now)
    if s["base_slots_remaining"] > 0:
        return None
    unused = (
        addons.filter(status="UNUSED")
        .filter(Q(activate_before__isnull=True) | Q(activate_before__gt=now))
        .order_by("granted_at", "unit_number", "id")
        .first()
    )
    if unused:
        return unused
    raise PropertyListingLimitReached(s)


def activate_unit(unit, listing):
    """Assign after the property has a persisted FK, inside the owner transaction."""
    unit.assigned_property = listing
    unit.status = "ACTIVE"
    unit.activated_at = timezone.now()
    unit.expires_at = unit.activated_at + timedelta(days=unit.duration_days)
    for previous in PropertyListingAddOn.objects.filter(
        assigned_property=listing, status="ACTIVE", expires_at__lte=unit.activated_at
    ):
        previous.status = "EXPIRED"
        previous.save()
    unit.save()


def check_submission(listing):
    # Review is not a live slot reservation. Approval rechecks under the same lock.
    with lock_owner(listing.owner_id, listing.agency_id):
        ensure_capacity(listing)


def resolve_scope(user, agency_id=None):
    if not agency_id:
        return user.pk, None
    from agencies.models import AgentProfile

    try:
        agency_id = uuid.UUID(str(agency_id))
    except ValueError:
        raise ValidationError({"agency": "A valid agency UUID is required."})
    if (
        not user.is_staff
        and not AgentProfile.objects.filter(
            user=user, agency_id=agency_id, is_active=True, agency__is_active=True
        ).exists()
    ):
        raise PermissionDenied("You must be active staff of this agency.")
    from agencies.models import Agency

    if not Agency.objects.filter(pk=agency_id).exists():
        raise ValidationError({"agency": "Agency not found."})
    return None, agency_id


def grant_package(
    package, *, actor, reason, account=None, agency=None, reference=None, provider="", transaction_reference=""
):
    """Admin only. One row per unit, with a shared purchase reference and exact total."""
    if not actor.is_staff or not reason.strip():
        raise PermissionDenied("Staff grant and reason required.")
    if bool(account) == bool(agency) or not package.is_active:
        raise ValidationError("Choose exactly one owner and an active package.")
    reference = reference or uuid.uuid4()
    with lock_owner(account.pk if account else None, agency.pk if agency else None):
        existing = PropertyListingAddOn.objects.filter(purchase_reference=reference)
        if existing.exists():
            if (
                existing.exclude(
                    **owner_filter(account.pk if account else None, agency.pk if agency else None)
                ).exists()
                or existing.exclude(source_package=package).exists()
            ):
                raise ValidationError("Purchase reference belongs to another owner.")
            return list(existing)
        units = []
        amounts = package_unit_amounts(package.price, package.quantity)
        for index in range(package.quantity):
            units.append(
                PropertyListingAddOn.objects.create(
                    account=account,
                    agency=agency,
                    source_package=package,
                    granted_by=actor,
                    grant_reason=reason,
                    provider=provider,
                    transaction_reference=transaction_reference,
                    purchase_reference=reference,
                    unit_number=index + 1,
                    duration_days=package.duration_days,
                    amount=amounts[index],
                    activate_before=(
                        timezone.now() + timedelta(days=package.purchase_validity_days)
                        if package.purchase_validity_days
                        else None
                    ),
                )
            )
        return units
