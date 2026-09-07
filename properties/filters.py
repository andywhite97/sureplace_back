import django_filters

from .models import Amenity, PropertyListing


class PropertyFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")
    min_bedrooms = django_filters.NumberFilter(field_name="bedrooms", lookup_expr="gte")
    min_bathrooms = django_filters.NumberFilter(field_name="bathrooms", lookup_expr="gte")
    amenities = django_filters.ModelMultipleChoiceFilter(queryset=Amenity.objects.filter(is_active=True))
    region = django_filters.CharFilter(lookup_expr="iexact")
    town = django_filters.CharFilter(lookup_expr="iexact")
    suburb = django_filters.CharFilter(lookup_expr="iexact")

    class Meta:
        model = PropertyListing
        fields = (
            "listing_type",
            "property_type",
            "region",
            "town",
            "suburb",
            "furnished",
            "pet_friendly",
            "amenities",
            "featured",
            "verification_status",
        )
