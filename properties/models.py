import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from core.choices import VerificationStatus
from core.models import TimeStampedModel
from .fields import location_field


class ListingType(models.TextChoices):
    RENT = "RENT", "For rent"
    SALE = "SALE", "For sale"


class PropertyType(models.TextChoices):
    HOUSE = "HOUSE", "House"
    APARTMENT = "APARTMENT", "Apartment"
    TOWNHOUSE = "TOWNHOUSE", "Townhouse"
    FLAT = "FLAT", "Flat"
    LAND = "LAND", "Land"
    OFFICE = "OFFICE", "Office"
    SHOP = "SHOP", "Shop"
    WAREHOUSE = "WAREHOUSE", "Warehouse"
    COMMERCIAL = "COMMERCIAL", "Commercial"
    OTHER = "OTHER", "Other"


class ListingStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    PUBLISHED = "PUBLISHED", "Published"
    CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
    PAUSED = "PAUSED", "Paused"
    EXPIRED = "EXPIRED", "Expired"
    REJECTED = "REJECTED", "Rejected"
    SUSPENDED = "SUSPENDED", "Suspended"


class AvailabilityStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    UNDER_OFFER = "UNDER_OFFER", "Under offer"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"
    UNKNOWN = "UNKNOWN", "Unknown"


class Amenity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    icon = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name


class PropertyListing(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=24, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="property_listings")
    agency = models.ForeignKey(
        "agencies.Agency", on_delete=models.SET_NULL, null=True, blank=True, related_name="property_listings"
    )
    agent = models.ForeignKey(
        "agencies.AgentProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="property_listings"
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, editable=False)
    description = models.TextField(blank=True)
    listing_type = models.CharField(max_length=8, choices=ListingType.choices)
    property_type = models.CharField(max_length=16, choices=PropertyType.choices)
    price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, default="SZL")
    country_code = models.CharField(max_length=2, default="SZ")
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    location = location_field()
    bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    parking_spaces = models.PositiveSmallIntegerField(default=0)
    floor_area = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))]
    )
    land_area = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))]
    )
    furnished = models.BooleanField(default=False)
    pet_friendly = models.BooleanField(default=False)
    amenities = models.ManyToManyField(Amenity, blank=True, related_name="properties")
    status = models.CharField(max_length=24, choices=ListingStatus.choices, default=ListingStatus.DRAFT)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    availability_status = models.CharField(
        max_length=16, choices=AvailabilityStatus.choices, default=AvailabilityStatus.UNKNOWN
    )
    availability_confirmed_at = models.DateTimeField(null=True, blank=True)
    featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("review_propertylisting", "Can review property listings"),
            ("approve_propertylisting", "Can approve property listings"),
            ("request_changes_propertylisting", "Can request changes on property listings"),
            ("reject_propertylisting", "Can reject property listings"),
            ("suspend_propertylisting", "Can suspend property listings"),
            ("restore_propertylisting", "Can restore property listings"),
            ("add_note_propertylisting", "Can add property moderation notes"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["featured", "status"]),
            models.Index(fields=["listing_type", "property_type"]),
            models.Index(fields=["region", "town", "suburb"]),
            models.Index(fields=["price"]),
        ]

    def __str__(self):
        return f"{self.public_id}: {self.title}"

    @staticmethod
    def _new_public_id():
        return f"SP-{date.today().year}-{uuid.uuid4().hex[:10].upper()}"

    def _set_unique_identifiers(self):
        if not self.public_id:
            candidate = self._new_public_id()
            while type(self).objects.filter(public_id=candidate).exists():
                candidate = self._new_public_id()
            self.public_id = candidate
        if not self.slug:
            base = slugify(self.title)[:240] or "property"
            candidate = base
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{uuid.uuid4().hex[:8]}"
            self.slug = candidate

    def clean(self):
        super().clean()
        errors = {}
        if self.agent_id and self.agency_id and self.agent.agency_id != self.agency_id:
            errors["agent"] = "The assigned agent must belong to the selected agency."
        if self.agent_id and not self.agency_id:
            self.agency_id = self.agent.agency_id
        if self.property_type == PropertyType.LAND and (
            self.bedrooms not in (None, 0) or self.bathrooms not in (None, 0)
        ):
            errors["property_type"] = "Land listings cannot have bedrooms or bathrooms."
        if self.status == ListingStatus.PUBLISHED:
            required = ("title", "description", "price", "region", "town", "location")
            missing = [field for field in required if getattr(self, field) in (None, "")]
            if missing:
                errors["status"] = f"Published listings require: {', '.join(missing)}."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self._set_unique_identifiers()
        if self.status == ListingStatus.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def latitude(self):
        if not self.location:
            return None
        return self.location.get("latitude") if isinstance(self.location, dict) else self.location.y

    @property
    def longitude(self):
        if not self.location:
            return None
        return self.location.get("longitude") if isinstance(self.location, dict) else self.location.x

    @property
    def cover_image(self):
        return self.images.filter(is_cover=True).first() or self.images.first()


class PropertyImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(PropertyListing, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="sureplace/properties/%Y/%m/")
    caption = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["property"], condition=models.Q(is_cover=True), name="one_cover_per_property"
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_cover and self.property_id:
                type(self).objects.filter(property_id=self.property_id, is_cover=True).exclude(pk=self.pk).update(
                    is_cover=False
                )
            super().save(*args, **kwargs)

    def __str__(self):
        return self.caption or f"Image for {self.property.public_id}"
