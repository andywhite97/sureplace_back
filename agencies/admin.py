from django.contrib import admin

from .models import Agency, AgentProfile


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "town", "region", "verification_status", "is_active", "created_at")
    list_filter = ("verification_status", "is_active", "region")
    search_fields = ("name", "email", "phone", "town", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "agency", "professional_reference", "verification_status", "is_active")
    list_filter = ("verification_status", "is_active", "agency")
    search_fields = ("user__email", "user__first_name", "user__last_name", "agency__name", "professional_reference")
    autocomplete_fields = ("user", "agency")
