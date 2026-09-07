from django.contrib import admin
from .models import Favourite


@admin.register(Favourite)
class FavouriteAdmin(admin.ModelAdmin):
    list_display = ("user", "property", "stay", "created_at")
    search_fields = ("user__email", "property__title", "stay__name")
