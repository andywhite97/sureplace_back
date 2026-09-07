from .filters import PropertyFilter
from .models import ListingStatus, PropertyListing


def property_search(criteria, queryset=None):
    qs = queryset or PropertyListing.objects.all()
    return PropertyFilter(criteria, queryset=qs.filter(status=ListingStatus.PUBLISHED)).qs.distinct()
