from django.contrib import admin

from .models import Agency, AgencyInvitation, AgentProfile


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "trading_name", "town", "region", "verification_status", "is_active", "created_at")
    list_filter = ("verification_status", "is_active", "region")
    search_fields = ("name", "email", "phone", "town", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "agency", "role", "professional_reference", "verification_status", "is_active")
    list_filter = ("role", "verification_status", "is_active", "agency")
    search_fields = ("user__email", "user__first_name", "user__last_name", "agency__name", "professional_reference")
    autocomplete_fields = ("user", "agency")


@admin.register(AgencyInvitation)
class AgencyInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "agency", "role", "status", "inviter", "expires_at", "created_at")
    list_filter = ("role", "status", "agency")
    search_fields = ("email", "agency__name", "inviter__email")
    autocomplete_fields = ("agency", "inviter", "accepted_by")
