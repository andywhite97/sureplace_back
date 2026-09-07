from django.contrib import admin
from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("user__email", "title")
    readonly_fields = ("user", "notification_type", "title", "message", "data", "event_key", "created_at")


admin.site.register(NotificationPreference)
