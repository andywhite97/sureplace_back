import uuid
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ViewingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED", "Reschedule requested"


class ViewingRequest(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(
        "properties.PropertyListing", on_delete=models.CASCADE, related_name="viewing_requests"
    )
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="viewing_requests")
    agent = models.ForeignKey(
        "agencies.AgentProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="viewing_requests"
    )
    conversation = models.ForeignKey(
        "messaging.Conversation", on_delete=models.SET_NULL, null=True, blank=True, related_name="viewing_requests"
    )
    requested_date = models.DateField()
    requested_time = models.TimeField()
    alternative_date = models.DateField(null=True, blank=True)
    alternative_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=ViewingStatus.choices, default=ViewingStatus.PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["requested_date", "requested_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "requester", "requested_date", "requested_time"],
                condition=models.Q(status__in=["PENDING", "CONFIRMED", "RESCHEDULE_REQUESTED"]),
                name="unique_active_viewing_request",
            )
        ]


class BookingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    DECLINED = "DECLINED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"
    EXPIRED = "EXPIRED", "Expired"


class PaymentStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"
    UNPAID = "UNPAID", "Unpaid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
    PAID = "PAID", "Paid"
    REFUNDED = "REFUNDED", "Refunded"
    FAILED = "FAILED", "Failed"


class Booking(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=32, unique=True, editable=False)
    stay = models.ForeignKey("stays.Stay", on_delete=models.PROTECT, related_name="bookings")
    room_type = models.ForeignKey("stays.RoomType", on_delete=models.PROTECT, related_name="bookings")
    guest = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stay_bookings")
    conversation = models.ForeignKey(
        "messaging.Conversation", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )
    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveSmallIntegerField()
    children = models.PositiveSmallIntegerField(default=0)
    rooms = models.PositiveSmallIntegerField()
    nightly_pricing = models.JSONField(default=list)
    nightly_subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    taxes = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    fees = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="SZL")
    status = models.CharField(max_length=12, choices=BookingStatus.choices, default=BookingStatus.PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    guest_name = models.CharField(max_length=200)
    guest_email = models.EmailField()
    guest_phone = models.CharField(max_length=20, blank=True)
    special_requests = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["guest", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="unique_guest_booking_idempotency",
            )
        ]
        indexes = [
            models.Index(fields=["guest", "-created_at"]),
            models.Index(fields=["stay", "status"]),
            models.Index(fields=["room_type", "check_in", "check_out"]),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            from datetime import date

            self.reference = f"SP-BKG-{date.today().year}-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)
