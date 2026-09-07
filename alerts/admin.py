from django.contrib import admin
from .models import SavedSearch, SearchAlertEvent


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "search_type", "frequency", "notifications_enabled", "last_checked_at")
    list_filter = ("search_type", "frequency", "notifications_enabled")
    search_fields = ("user__email", "name")


@admin.register(SearchAlertEvent)
class EventAdmin(admin.ModelAdmin):
    list_display = ("saved_search", "listing_type", "discovered_at", "notified_at")
    list_filter = ("listing_type", "notified_at")
    search_fields = ("saved_search__user__email",)
