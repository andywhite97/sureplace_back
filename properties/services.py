from rest_framework.exceptions import APIException
from django.utils import timezone

from .models import AvailabilityStatus, ListingStatus


class InvalidListingTransition(APIException):
    status_code = 409
    default_code = "invalid_listing_transition"

    def __init__(self, detail):
        super().__init__({"code": self.default_code, "detail": detail})


def submit_listing(listing):
    if listing.status not in {ListingStatus.DRAFT, ListingStatus.REJECTED, ListingStatus.CHANGES_REQUESTED}:
        if listing.status == ListingStatus.PUBLISHED:
            raise InvalidListingTransition("This property is already approved and published.")
        raise InvalidListingTransition("Only draft, rejected or changes-requested listings can be submitted.")
    listing.status = ListingStatus.PUBLISHED
    listing.full_clean()
    listing.status = ListingStatus.SUBMITTED
    listing.save(update_fields=["status", "updated_at"])
    return listing


def pause_listing(listing):
    if listing.status != ListingStatus.PUBLISHED:
        raise ValidationError("Only published listings can be paused.")
    listing.status = ListingStatus.PAUSED
    listing.save(update_fields=["status", "updated_at"])
    return listing


def confirm_availability(listing):
    listing.availability_status = AvailabilityStatus.AVAILABLE
    listing.availability_confirmed_at = timezone.now()
    listing.save(update_fields=["availability_status", "availability_confirmed_at", "updated_at"])
    return listing


def listing_quality(listing):
    score = 0
    suggestions = []
    checks = [
        (bool(listing.title), 10, "Add a title"),
        (len(listing.description.strip()) >= 100, 15, "Add a more detailed description"),
        (listing.price is not None, 10, "Add a price"),
        (bool(listing.location), 15, "Add a map location"),
        (bool(listing.region and listing.town), 10, "Add the region and town"),
        (listing.property_type == "LAND" or listing.bedrooms is not None, 10, "Add property details"),
        (listing.amenities.count() >= 3, 10, "Add more amenities"),
        (listing.images.count() >= 5, 15, "Add more photos to improve your listing"),
        (listing.availability_confirmed_at is not None, 5, "Confirm availability"),
    ]
    for complete, points, suggestion in checks:
        if complete:
            score += points
        else:
            suggestions.append(suggestion)
    return {"score": min(score, 100), "suggestions": suggestions}
