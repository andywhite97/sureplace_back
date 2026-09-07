from django.contrib import admin

from .models import Amenity, PropertyImage, PropertyListing


class PropertyImageInline(admin.TabularInline):
    model = PropertyImage
    extra = 0
    ordering = ("sort_order",)


@admin.register(PropertyListing)
class PropertyListingAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "title",
        "listing_type",
        "property_type",
        "town",
        "price",
        "status",
        "verification_status",
        "availability_status",
        "featured",
        "created_at",
    )
    list_filter = (
        "listing_type",
        "property_type",
        "status",
        "verification_status",
        "availability_status",
        "featured",
        "region",
    )
    search_fields = ("public_id", "title", "slug", "town", "suburb", "owner__email", "agency__name")
    readonly_fields = ("public_id", "slug", "published_at", "created_at", "updated_at")
    autocomplete_fields = ("owner", "agency", "agent")
    filter_horizontal = ("amenities",)
    inlines = (PropertyImageInline,)


@admin.register(PropertyImage)
class PropertyImageAdmin(admin.ModelAdmin):
    list_display = ("property", "caption", "sort_order", "is_cover", "created_at")
    list_filter = ("is_cover",)
    search_fields = ("property__public_id", "property__title", "caption")
    autocomplete_fields = ("property",)


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "icon", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
