import uuid
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ReportReason(models.TextChoices):
    SCAM = "SCAM", "Scam"
    DUPLICATE = "DUPLICATE", "Duplicate"
    INCORRECT = "INCORRECT", "Incorrect information"
    UNAVAILABLE = "UNAVAILABLE", "Unavailable"
    INAPPROPRIATE = "INAPPROPRIATE", "Inappropriate content"
    OTHER = "OTHER", "Other"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    RESOLVED = "RESOLVED", "Resolved"
    DISMISSED = "DISMISSED", "Dismissed"


class ListingReport(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    property = models.ForeignKey("properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True)
    stay = models.ForeignKey("stays.Stay", on_delete=models.CASCADE, null=True, blank=True)
    reason = models.CharField(max_length=30, choices=ReportReason.choices)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_reports"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(property__isnull=False, stay__isnull=True)
                    | models.Q(property__isnull=True, stay__isnull=False)
                ),
                name="report_exactly_one_listing",
            )
        ]
        indexes = [models.Index(fields=["status", "-created_at"])]


class ModerationAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40)
    property = models.ForeignKey("properties.PropertyListing", on_delete=models.SET_NULL, null=True, blank=True)
    stay = models.ForeignKey("stays.Stay", on_delete=models.SET_NULL, null=True, blank=True)
    report = models.ForeignKey(ListingReport, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
