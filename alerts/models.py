import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.models import TimeStampedModel


class SearchType(models.TextChoices):
    PROPERTY = "PROPERTY", "Property"
    STAY = "STAY", "Stay"


class Frequency(models.TextChoices):
    INSTANT = "INSTANT", "Instant"
    DAILY = "DAILY", "Daily"
    WEEKLY = "WEEKLY", "Weekly"
    OFF = "OFF", "Off"


class SavedSearch(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=200, blank=True)
    search_type = models.CharField(max_length=10, choices=SearchType.choices)
    criteria = models.JSONField(default=dict)
    notifications_enabled = models.BooleanField(default=True)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.DAILY)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        if self.frequency == Frequency.OFF:
            self.notifications_enabled = False


class SearchAlertEvent(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    saved_search = models.ForeignKey(SavedSearch, on_delete=models.CASCADE, related_name="events")
    listing_type = models.CharField(max_length=10, choices=SearchType.choices)
    property = models.ForeignKey(
        "properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True, related_name="alert_events"
    )
    stay = models.ForeignKey("stays.Stay", on_delete=models.CASCADE, null=True, blank=True, related_name="alert_events")
    discovered_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-discovered_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(property__isnull=False, stay__isnull=True)
                    | models.Q(property__isnull=True, stay__isnull=False)
                ),
                name="alert_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["saved_search", "property"],
                condition=models.Q(property__isnull=False),
                name="unique_search_property_event",
            ),
            models.UniqueConstraint(
                fields=["saved_search", "stay"], condition=models.Q(stay__isnull=False), name="unique_search_stay_event"
            ),
        ]

    def clean(self):
        if bool(self.property_id) == bool(self.stay_id):
            raise ValidationError("Exactly one target is required.")
