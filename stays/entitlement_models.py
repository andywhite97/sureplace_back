import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.utils import timezone
from core.entitlement_models import AuditedListingGrant
from core.entitlement_utils import owner_constraints


class StayPlan(models.Model):
    code = models.CharField(max_length=32, primary_key=True)
    display_name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    billing_interval = models.CharField(max_length=12, choices=[("FOREVER", "Forever"), ("MONTH", "Month")])
    active_listing_limit = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "code"]
        constraints = [models.CheckConstraint(condition=Q(price__gte=0), name="stay_plan_price_nonnegative")]

    def clean(self):
        if self.code == "HOST_FREE" and (self.price != 0 or self.billing_interval != "FOREVER" or not self.is_active):
            raise ValidationError("Host Free must remain an active, free, non-recurring plan.")

    def __str__(self):
        return self.display_name


class StayAddOnPackage(models.Model):
    code = models.CharField(max_length=32, primary_key=True)
    display_name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    duration_days = models.PositiveIntegerField(default=90)
    purchase_validity_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "code"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="stay_package_price_nonnegative"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0, duration_days__gt=0), name="stay_package_positive_units"
            ),
        ]

    def __str__(self):
        return self.display_name


class StayPromotion(models.Model):
    code = models.CharField(max_length=32, primary_key=True)
    display_name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=7)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(price__gte=0, duration_days__gt=0), name="stay_promotion_positive_values"
            )
        ]

    def __str__(self):
        return self.display_name


AUDIT_FIELDS = (
    "account_id",
    "agency_id",
    "granted_by_id",
    "grant_reason",
    "granted_at",
    "provider",
    "transaction_reference",
    "amount",
)


class StayGrant(AuditedListingGrant):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        # Validate current authority on grant creation, not against historic actors
        # during scheduled expiry after a staff member has left the organisation.
        if self._state.adding and self.granted_by_id:
            actor = self.granted_by
            if not actor.is_active or not actor.is_staff or not actor.has_perm(f"stays.add_{self._meta.model_name}"):
                raise ValidationError("An active staff member with grant permission must authorize this entitlement.")


class StaySubscription(StayGrant):
    plan = models.ForeignKey(StayPlan, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        max_length=12,
        choices=[("ACTIVE", "Active"), ("GRACE", "Grace"), ("EXPIRED", "Expired"), ("CANCELLED", "Cancelled")],
        default="ACTIVE",
    )
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    grace_until = models.DateTimeField(blank=True)
    grace_entered_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=False)

    class Meta:
        constraints = owner_constraints("stay_subscription") + [
            models.UniqueConstraint(
                fields=["account"],
                condition=Q(status__in=["ACTIVE", "GRACE"], account__isnull=False),
                name="one_stay_subscription_account",
            ),
            models.UniqueConstraint(
                fields=["agency"],
                condition=Q(status__in=["ACTIVE", "GRACE"], agency__isnull=False),
                name="one_stay_subscription_agency",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("starts_at"), grace_until__gte=F("expires_at"), amount__gte=0),
                name="stay_subscription_valid_dates",
            ),
            models.CheckConstraint(condition=Q(auto_renew=False), name="stay_subscription_no_auto_renewal"),
        ]

    def clean(self):
        super().clean()
        if self._state.adding:
            if self.plan_id and not self.plan.is_active:
                raise ValidationError({"plan": "Choose an active plan."})
            if self.plan_id:
                self.amount = self.plan.price
            if self.expires_at:
                self.grace_until = self.expires_at + timedelta(days=max(0, settings.STAY_SUBSCRIPTION_GRACE_DAYS))
        else:
            old = type(self).objects.get(pk=self.pk)
            if any(
                getattr(old, field) != getattr(self, field)
                for field in AUDIT_FIELDS + ("plan_id", "starts_at", "expires_at", "grace_until")
            ):
                raise ValidationError(
                    "Subscription grant history is immutable. Cancel and grant a replacement to renew or change plan."
                )
        if self.auto_renew:
            raise ValidationError({"auto_renew": "Verified recurring payments are not configured."})


class StayListingAddOn(StayGrant):
    source_package = models.ForeignKey(StayAddOnPackage, on_delete=models.PROTECT)
    assigned_stay = models.ForeignKey(
        "stays.Stay", null=True, blank=True, on_delete=models.PROTECT, related_name="listing_addons"
    )
    purchase_reference = models.UUIDField(default=uuid.uuid4, editable=False)
    unit_number = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=90)
    activate_before = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    expiry_processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=[("UNUSED", "Unused"), ("ACTIVE", "Active"), ("EXPIRED", "Expired")], default="UNUSED"
    )

    class Meta:
        constraints = owner_constraints("stay_addon") + [
            models.UniqueConstraint(
                fields=["purchase_reference", "unit_number"], name="unique_stay_addon_purchase_unit"
            ),
            models.UniqueConstraint(
                fields=["assigned_stay"], condition=Q(status="ACTIVE"), name="one_active_addon_per_stay"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0, duration_days__gt=0, unit_number__gt=0), name="stay_addon_positive_values"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="UNUSED", assigned_stay__isnull=True, activated_at__isnull=True, expires_at__isnull=True)
                    | Q(
                        status__in=["ACTIVE", "EXPIRED"],
                        assigned_stay__isnull=False,
                        activated_at__isnull=False,
                        expires_at__gt=F("activated_at"),
                    )
                ),
                name="stay_addon_activation_dates",
            ),
        ]

    def clean(self):
        super().clean()
        if self._state.adding and self.source_package_id and not self.source_package.is_active:
            raise ValidationError({"source_package": "Choose an active package."})
        if self.assigned_stay_id:
            stay = self.assigned_stay
            if stay.agency_id != self.agency_id or (not self.agency_id and stay.owner_id != self.account_id):
                raise ValidationError({"assigned_stay": "The stay must belong to this entitlement's owner scope."})
        old = type(self).objects.filter(pk=self.pk).first()
        if old and any(
            getattr(old, field) != getattr(self, field)
            for field in AUDIT_FIELDS
            + ("source_package_id", "purchase_reference", "unit_number", "duration_days", "activate_before")
        ):
            raise ValidationError("Purchase/grant history is immutable. Grant a new unit to renew.")
        if (
            old
            and old.activated_at
            and any(
                getattr(old, field) != getattr(self, field)
                for field in ("assigned_stay_id", "activated_at", "expires_at")
            )
        ):
            raise ValidationError("An activated stay allowance cannot be extended or reassigned.")


class StayCapacityReview(models.Model):
    stay = models.OneToOneField(
        "stays.Stay", primary_key=True, on_delete=models.PROTECT, related_name="capacity_review"
    )
    reason = models.CharField(
        max_length=32,
        choices=[
            ("ADDON_EXPIRED", "Add-on expired"),
            ("SUBSCRIPTION_EXPIRED", "Subscription expired or cancelled"),
            ("LEGACY_OVER_LIMIT", "Legacy over limit"),
        ],
    )
    status = models.CharField(
        max_length=24,
        choices=[("PROTECTED_BOOKINGS", "Protected bookings"), ("OVER_LIMIT", "Over limit"), ("RESOLVED", "Resolved")],
    )
    expired_addon = models.ForeignKey(StayListingAddOn, null=True, blank=True, on_delete=models.PROTECT)
    pause_when_safe = models.BooleanField(default=False)
    opened_at = models.DateTimeField(default=timezone.now)
    last_checked_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status="RESOLVED", resolved_at__isnull=False)
                    | Q(status__in=["PROTECTED_BOOKINGS", "OVER_LIMIT"], resolved_at__isnull=True)
                ),
                name="stay_review_resolution_date",
            )
        ]
