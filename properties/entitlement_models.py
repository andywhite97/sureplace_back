"""Property-only pricing and auditable, administrator-granted entitlements."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.utils import timezone
from core.entitlement_models import AuditedListingGrant
from core.entitlement_utils import owner_constraints


class PropertyPlan(models.Model):
    code = models.CharField(max_length=32, primary_key=True)
    display_name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    billing_interval = models.CharField(max_length=12, choices=[("FOREVER", "Forever"), ("MONTH", "Month")])
    active_listing_limit = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    applicable_account_types = models.JSONField(default=list)

    class Meta:
        ordering = ["display_order", "code"]
        constraints = [models.CheckConstraint(condition=Q(price__gte=0), name="property_plan_price_nonnegative")]

    def clean(self):
        if not self.applicable_account_types or set(self.applicable_account_types) - {"INDIVIDUAL", "AGENCY"}:
            raise ValidationError({"applicable_account_types": "Choose INDIVIDUAL and/or AGENCY."})
        if self.code in {"INDIVIDUAL_FREE", "AGENCY_FREE"} and self.price != 0:
            raise ValidationError({"price": "Default free plans must remain free."})

    def __str__(self):
        return self.display_name


class PropertyAddOnPackage(models.Model):
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
            models.CheckConstraint(condition=Q(price__gte=0), name="property_package_price_nonnegative"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0, duration_days__gt=0), name="property_package_positive_units"
            ),
        ]

    def __str__(self):
        return self.display_name


class PropertyGrant(AuditedListingGrant):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        # Preserve the Phase 1 grant validation behavior.
        if not self.granted_by_id or not self.granted_by.is_staff:
            raise ValidationError("Paid grants require a staff actor and a documented reason.")


class PropertySubscription(PropertyGrant):
    plan = models.ForeignKey(PropertyPlan, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=12, choices=[("ACTIVE", "Active"), ("CANCELLED", "Cancelled")], default="ACTIVE"
    )
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    auto_renew = models.BooleanField(default=False)

    class Meta:
        constraints = owner_constraints("property_subscription") + [
            models.UniqueConstraint(
                fields=["account"],
                condition=Q(status="ACTIVE", account__isnull=False),
                name="one_property_subscription_account",
            ),
            models.UniqueConstraint(
                fields=["agency"],
                condition=Q(status="ACTIVE", agency__isnull=False),
                name="one_property_subscription_agency",
            ),
            models.CheckConstraint(condition=Q(expires_at__gt=F("starts_at")), name="property_subscription_dates"),
            models.CheckConstraint(condition=Q(auto_renew=False), name="property_subscription_no_unverified_renewal"),
        ]

    def clean(self):
        super().clean()
        if self.plan_id:
            kind = "AGENCY" if self.agency_id else "INDIVIDUAL"
            if kind not in self.plan.applicable_account_types or not self.plan.is_active:
                raise ValidationError({"plan": "This plan is not available for this account type."})
        if self.auto_renew:
            raise ValidationError({"auto_renew": "Verified recurring payments are not configured."})


class PropertyListingAddOn(PropertyGrant):
    source_package = models.ForeignKey(PropertyAddOnPackage, on_delete=models.PROTECT)
    assigned_property = models.ForeignKey(
        "properties.PropertyListing", null=True, blank=True, on_delete=models.PROTECT, related_name="listing_addons"
    )
    purchase_reference = models.UUIDField(default=uuid.uuid4, editable=False)
    unit_number = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=90)
    activate_before = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=[("UNUSED", "Unused"), ("ACTIVE", "Active"), ("EXPIRED", "Expired")], default="UNUSED"
    )

    class Meta:
        constraints = owner_constraints("property_addon") + [
            models.UniqueConstraint(
                fields=["purchase_reference", "unit_number"], name="unique_property_addon_purchase_unit"
            ),
            models.UniqueConstraint(
                fields=["assigned_property"], condition=Q(status="ACTIVE"), name="one_active_addon_per_property"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0, duration_days__gt=0, unit_number__gt=0),
                name="property_addon_positive_values",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="UNUSED",
                        assigned_property__isnull=True,
                        activated_at__isnull=True,
                        expires_at__isnull=True,
                    )
                    | Q(
                        status__in=["ACTIVE", "EXPIRED"],
                        assigned_property__isnull=False,
                        activated_at__isnull=False,
                        expires_at__gt=F("activated_at"),
                    )
                ),
                name="property_addon_activation_dates",
            ),
        ]

    def clean(self):
        super().clean()
        if self._state.adding and self.source_package_id and not self.source_package.is_active:
            raise ValidationError({"source_package": "Choose an active package."})
        if self.assigned_property_id:
            p = self.assigned_property
            if p.agency_id != self.agency_id or (not self.agency_id and p.owner_id != self.account_id):
                raise ValidationError(
                    {"assigned_property": "The property must belong to this entitlement's account or agency."}
                )
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if (
                old
                and old.activated_at
                and any(
                    getattr(old, f) != getattr(self, f)
                    for f in (
                        "assigned_property_id",
                        "account_id",
                        "agency_id",
                        "activated_at",
                        "expires_at",
                        "duration_days",
                        "amount",
                        "purchase_reference",
                        "unit_number",
                        "source_package_id",
                        "granted_by_id",
                        "grant_reason",
                        "provider",
                        "transaction_reference",
                    )
                )
            ):
                raise ValidationError("Activated entitlement history is immutable. Grant a new unit to renew.")
