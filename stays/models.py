import uuid
from datetime import date
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify
from accounts.models import phone_validator
from core.choices import VerificationStatus
from core.models import TimeStampedModel
from properties.fields import location_field


class StayType(models.TextChoices):
    HOTEL = "HOTEL", "Hotel"
    GUEST_HOUSE = "GUEST_HOUSE", "Guest house"
    LODGE = "LODGE", "Lodge"
    BNB = "BNB", "B&B"
    SELF_CATERING = "SELF_CATERING", "Self catering"
    SHORT_STAY = "SHORT_STAY", "Short stay"
    RESORT = "RESORT", "Resort"
    HOSTEL = "HOSTEL", "Hostel"
    OTHER = "OTHER", "Other"


class StayStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    PUBLISHED = "PUBLISHED", "Published"
    PAUSED = "PAUSED", "Paused"
    REJECTED = "REJECTED", "Rejected"
    SUSPENDED = "SUSPENDED", "Suspended"


class StayAmenity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name_plural = "stay amenities"

    def __str__(self):
        return self.name


class Stay(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=30, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stays")
    agency = models.ForeignKey(
        "agencies.Agency", on_delete=models.SET_NULL, null=True, blank=True, related_name="stays"
    )
    agent = models.ForeignKey(
        "agencies.AgentProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="stays"
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, editable=False)
    description = models.TextField(blank=True)
    stay_type = models.CharField(max_length=20, choices=StayType.choices)
    country_code = models.CharField(max_length=2, default="SZ")
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    location = location_field()
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    whatsapp_number = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    website = models.URLField(blank=True)
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    amenities = models.ManyToManyField(StayAmenity, blank=True, related_name="stays")
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    status = models.CharField(max_length=16, choices=StayStatus.choices, default=StayStatus.DRAFT)
    featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["stay_type", "status"]),
            models.Index(fields=["featured", "status"]),
            models.Index(fields=["region", "town", "suburb"]),
        ]

    def __str__(self):
        return f"{self.public_id}: {self.name}"

    def clean(self):
        if self.agent_id and self.agency_id and self.agent.agency_id != self.agency_id:
            raise ValidationError({"agent": "Agent must belong to the selected agency."})
        if self.agent_id and not self.agency_id:
            self.agency_id = self.agent.agency_id
        if self.status == StayStatus.PUBLISHED and any(
            getattr(self, f) in (None, "") for f in ("name", "description", "region", "town", "location")
        ):
            raise ValidationError({"status": "Published stays require name, description, region, town, and location."})

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = f"SP-STAY-{date.today().year}-{uuid.uuid4().hex[:10].upper()}"
        if not self.slug:
            base = slugify(self.name)[:240] or "stay"
            candidate = base
            while type(self).objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{uuid.uuid4().hex[:8]}"
            self.slug = candidate
        if self.status == StayStatus.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def latitude(self):
        return (
            None
            if not self.location
            else (self.location.get("latitude") if isinstance(self.location, dict) else self.location.y)
        )

    @property
    def longitude(self):
        return (
            None
            if not self.location
            else (self.location.get("longitude") if isinstance(self.location, dict) else self.location.x)
        )

    @property
    def cover_image(self):
        return self.images.filter(is_cover=True).first() or self.images.first()


class OrderedCoverImage(models.Model):
    image = models.ImageField(upload_to="sureplace/stays/%Y/%m/")
    caption = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["sort_order", "created_at"]


class StayImage(OrderedCoverImage):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stay = models.ForeignKey(Stay, on_delete=models.CASCADE, related_name="images")

    class Meta(OrderedCoverImage.Meta):
        constraints = [
            models.UniqueConstraint(fields=["stay"], condition=models.Q(is_cover=True), name="one_cover_per_stay")
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_cover:
                type(self).objects.filter(stay=self.stay, is_cover=True).exclude(pk=self.pk).update(is_cover=False)
            super().save(*args, **kwargs)


class RoomType(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stay = models.ForeignKey(Stay, on_delete=models.CASCADE, related_name="room_types")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True)
    capacity_adults = models.PositiveSmallIntegerField(default=1)
    capacity_children = models.PositiveSmallIntegerField(default=0)
    total_capacity = models.PositiveSmallIntegerField(default=1)
    number_of_beds = models.PositiveSmallIntegerField(default=1)
    bed_configuration = models.CharField(max_length=255, blank=True)
    bathroom_type = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    base_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, default="SZL")
    minimum_stay = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["base_price", "name"]
        constraints = [models.UniqueConstraint(fields=["stay", "slug"], name="unique_room_slug_per_stay")]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:160] or uuid.uuid4().hex[:8]
        super().save(*args, **kwargs)

    def clean(self):
        if self.total_capacity < self.capacity_adults + self.capacity_children:
            raise ValidationError({"total_capacity": "Must cover adult and child capacities."})

    def effective_price(self, on_date):
        row = self.availability.filter(date=on_date).first()
        return row.custom_price if row and row.custom_price is not None else self.base_price


class RoomTypeImage(OrderedCoverImage):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    image = models.ImageField(upload_to="sureplace/rooms/%Y/%m/")
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="images")

    class Meta(OrderedCoverImage.Meta):
        constraints = [
            models.UniqueConstraint(fields=["room_type"], condition=models.Q(is_cover=True), name="one_cover_per_room")
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_cover:
                type(self).objects.filter(room_type=self.room_type, is_cover=True).exclude(pk=self.pk).update(
                    is_cover=False
                )
            super().save(*args, **kwargs)


class RoomAvailability(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="availability")
    date = models.DateField()
    available_units = models.PositiveIntegerField()
    custom_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))]
    )
    minimum_stay_override = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    is_blocked = models.BooleanField(default=False)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["room_type", "date"], name="unique_room_availability_date")]

    def clean(self):
        if self.room_type_id and self.available_units > self.room_type.quantity:
            raise ValidationError({"available_units": "Cannot exceed room quantity."})
