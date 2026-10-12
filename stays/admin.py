from django.contrib import admin
from .models import *
from . import pricing_admin  # noqa: F401


class StayImageInline(admin.TabularInline):
    model = StayImage
    extra = 0


class RoomInline(admin.TabularInline):
    model = RoomType
    extra = 0


@admin.register(Stay)
class StayAdmin(admin.ModelAdmin):
    list_display = ("public_id", "name", "stay_type", "town", "status", "verification_status", "featured")
    list_filter = ("stay_type", "status", "verification_status", "featured")
    search_fields = ("public_id", "name", "town", "owner__email")
    inlines = (StayImageInline, RoomInline)

    def save_model(self, request, obj, form, change):
        from core.entitlement_utils import lock_owner
        with lock_owner(obj.owner_id, obj.agency_id):
            # Room inlines are saved later in the admin transaction. Acquire
            # their locks before the stay row, just like bookings and expiry.
            list(RoomType.objects.select_for_update(of=("self",)).filter(stay=obj).order_by("pk"))
            super().save_model(request, obj, form, change)


@admin.register(RoomType)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "stay", "base_price", "quantity", "is_active")
    list_filter = ("is_active", "currency")
    search_fields = ("name", "stay__name")


admin.site.register(StayImage)
admin.site.register(StayAmenity)
admin.site.register(RoomTypeImage)
admin.site.register(RoomAvailability)
