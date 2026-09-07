from django.contrib import admin
from .models import Booking, ViewingRequest


@admin.register(ViewingRequest)
class ViewingAdmin(admin.ModelAdmin):
    list_display = ("property", "requester", "requested_date", "status")
    list_filter = ("status", "requested_date")
    search_fields = ("property__public_id", "requester__email")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "stay",
        "room_type",
        "guest",
        "status",
        "payment_status",
        "check_in",
        "check_out",
        "created_at",
    )
    list_filter = ("status", "payment_status", "stay", "check_in")
    search_fields = ("reference", "guest_name", "guest_email", "stay__name")
    readonly_fields = ("nightly_pricing", "nightly_subtotal", "taxes", "fees", "total")
