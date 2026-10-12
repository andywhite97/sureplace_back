from django.contrib import admin
from core.entitlement_admin import GrantAdmin
from .entitlement_models import PropertyPlan, PropertyAddOnPackage, PropertySubscription, PropertyListingAddOn
from .entitlements import grant_package, lock_owner


@admin.register(PropertyPlan)
class PropertyPlanAdmin(admin.ModelAdmin):
    list_display = ("display_name", "price", "active_listing_limit", "is_active", "display_order")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PropertyAddOnPackage)
class PropertyAddOnPackageAdmin(admin.ModelAdmin):
    list_display = ("display_name", "price", "quantity", "duration_days", "is_active")


@admin.register(PropertySubscription)
class PropertySubscriptionAdmin(GrantAdmin):
    list_display = ("account", "agency", "plan", "status", "starts_at", "expires_at")

    def save_model(self, request, obj, form, change):
        with lock_owner(obj.account_id, obj.agency_id):
            if not change:
                obj.granted_by = request.user
            super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("account", "agency") if obj else ())


@admin.register(PropertyListingAddOn)
class PropertyListingAddOnAdmin(GrantAdmin):
    list_display = ("account", "agency", "source_package", "unit_number", "status", "assigned_property", "expires_at")
    readonly_fields = GrantAdmin.readonly_fields + (
        "amount",
        "purchase_reference",
        "unit_number",
        "duration_days",
        "status",
        "assigned_property",
        "activated_at",
        "expires_at",
        "activate_before",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(f.name for f in self.model._meta.fields)
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if change:
            return
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
        # Admin logs the first unit; every sibling carries the same staff/reason/reference.
        obj.__dict__.update(units[0].__dict__)
