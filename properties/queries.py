from .filters import PropertyFilter
from .models import AvailabilityStatus, ListingStatus, PropertyListing


def property_search(criteria, queryset=None):
    qs = queryset or PropertyListing.objects.all()
    return PropertyFilter(criteria, queryset=qs.filter(status=ListingStatus.PUBLISHED, availability_status=AvailabilityStatus.AVAILABLE)).qs.distinct()
