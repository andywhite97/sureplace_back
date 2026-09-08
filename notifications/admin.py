from django.contrib import admin
from .models import EmailDelivery, Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("user__email", "title")
    readonly_fields = ("user", "notification_type", "title", "message", "data", "event_key", "created_at")


admin.site.register(NotificationPreference)


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ("recipient", "subject", "provider", "provider_message_id", "status", "attempts", "created_at")
    list_filter = ("provider", "status", "template_key")
    search_fields = ("recipient", "subject", "provider_message_id")
    readonly_fields = (
        "notification",
        "recipient",
        "subject",
        "provider",
        "provider_message_id",
        "template_key",
        "status",
        "attempts",
        "last_error_code",
        "last_error_message",
        "created_at",
        "accepted_at",
        "delivered_at",
        "failed_at",
    )
