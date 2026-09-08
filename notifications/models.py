import uuid
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class NotificationType(models.TextChoices):
    NEW_MESSAGE = "NEW_MESSAGE", "New message"
    GUEST_ENQUIRY = "GUEST_ENQUIRY", "Guest enquiry"
    VIEWING_REQUEST = "VIEWING_REQUEST", "Viewing request"
    VIEWING_CONFIRMED = "VIEWING_CONFIRMED", "Viewing confirmed"
    VIEWING_RESCHEDULED = "VIEWING_RESCHEDULED", "Viewing rescheduled"
    VIEWING_CANCELLED = "VIEWING_CANCELLED", "Viewing cancelled"
    BOOKING_REQUESTED = "BOOKING_REQUESTED", "Booking requested"
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking confirmed"
    BOOKING_DECLINED = "BOOKING_DECLINED", "Booking declined"
    BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking cancelled"
    BOOKING_EXPIRING = "BOOKING_EXPIRING", "Booking expiring"
    SAVED_SEARCH_MATCH = "SAVED_SEARCH_MATCH", "Saved-search match"
    LISTING_AVAILABILITY_REMINDER = "LISTING_AVAILABILITY_REMINDER", "Availability reminder"
    LISTING_STATUS_UPDATE = "LISTING_STATUS_UPDATE", "Listing status"
    VERIFICATION_UPDATE = "VERIFICATION_UPDATE", "Verification"
    SYSTEM = "SYSTEM", "System"


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    event_key = models.CharField(max_length=200, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "event_key"],
                condition=models.Q(event_key__isnull=False),
                name="unique_notification_event",
            )
        ]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]


class NotificationPreference(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference"
    )
    email_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    new_message_email = models.BooleanField(default=True)
    viewing_updates_email = models.BooleanField(default=True)
    booking_updates_email = models.BooleanField(default=True)
    saved_search_email = models.BooleanField(default=True)
    listing_reminders_email = models.BooleanField(default=True)
    marketing_email = models.BooleanField(default=False)


class EmailDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.SET_NULL, null=True, blank=True, related_name="email_deliveries"
    )
    recipient = models.EmailField()
    subject = models.CharField(max_length=998)
    provider = models.CharField(max_length=40, blank=True)
    provider_message_id = models.CharField(max_length=120, blank=True)
    template_key = models.CharField(max_length=80, default="transactional")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=100, blank=True)
    last_error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "provider_message_id"]),
            models.Index(fields=["status", "-created_at"]),
        ]
