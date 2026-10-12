from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from rest_framework.exceptions import APIException
from core.entitlement_admin import GrantAdmin
from core.entitlement_utils import lock_owner
from .models import StayPlan, StayAddOnPackage, StaySubscription, StayListingAddOn, StayPromotion, StayCapacityReview
from .entitlements import grant_package, allocate_renewal


@admin.register(StayPlan)
class StayPlanAdmin(admin.ModelAdmin):
    list_display = ("display_name", "price", "active_listing_limit", "is_active", "display_order")

    def get_readonly_fields(self, request, obj=None):
        return ("code",) if obj else ()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StayAddOnPackage)
class StayAddOnPackageAdmin(admin.ModelAdmin):
    list_display = ("display_name", "price", "quantity", "duration_days", "is_active")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StayPromotion)
class StayPromotionAdmin(admin.ModelAdmin):
    list_display = ("display_name", "price", "duration_days")
    readonly_fields = ("code", "display_name", "price", "duration_days", "is_active")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StaySubscription)
class StaySubscriptionAdmin(GrantAdmin):
    list_display = ("account", "agency", "plan", "status", "expires_at", "grace_until")
    readonly_fields = GrantAdmin.readonly_fields + (
        "amount",
        "grace_until",
        "grace_entered_at",
        "expired_at",
        "auto_renew",
    )

    def get_readonly_fields(self, request, obj=None):
        return (
            tuple(field.name for field in self.model._meta.fields if field.name != "status")
            if obj
            else self.readonly_fields
        )

    def save_model(self, request, obj, form, change):
        with lock_owner(obj.account_id, obj.agency_id):
            if not change:
                obj.granted_by = request.user
            super().save_model(request, obj, form, change)


@admin.register(StayListingAddOn)
class StayListingAddOnAdmin(GrantAdmin):
    list_display = ("account", "agency", "source_package", "unit_number", "status", "assigned_stay", "expires_at")
    readonly_fields = GrantAdmin.readonly_fields + (
        "amount",
        "purchase_reference",
        "unit_number",
        "duration_days",
        "status",
        "assigned_stay",
        "activated_at",
        "expires_at",
        "expiry_processed_at",
        "activate_before",
    )

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            units = grant_package(
                obj.source_package,
                actor=request.user,
                reason=obj.grant_reason,
                account=obj.account,
                agency=obj.agency,
                reference=obj.purchase_reference,
                provider=obj.provider,
                transaction_reference=obj.transaction_reference,
            )
            obj.__dict__.update(units[0].__dict__)


@admin.register(StayCapacityReview)
class StayCapacityReviewAdmin(admin.ModelAdmin):
    list_display = ("stay", "reason", "status", "pause_when_safe", "opened_at", "last_checked_at")
    list_filter = ("status", "reason", "pause_when_safe")
    readonly_fields = tuple(field.name for field in StayCapacityReview._meta.fields)
    actions = ("renew_from_granted_unit",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Allocate a granted extra unit to renew selected stays", permissions=["change"])
    def renew_from_granted_unit(self, request, queryset):
        count = 0
        for review in queryset.select_related("stay"):
            try:
                allocate_renewal(review.stay, actor=request.user)
                count += 1
            except (ValidationError, APIException) as error:
                self.message_user(request, f"{review.stay.name}: {error}", messages.ERROR)
        self.message_user(
            request, f"{count} stay allowance(s) allocated from existing audited grants.", messages.SUCCESS
        )
