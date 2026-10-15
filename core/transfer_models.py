import uuid
from django.conf import settings
from django.db import models
from .models import TimeStampedModel


class ListingTransfer(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=8, choices=[("property", "Property"), ("stay", "Stay")])
    listing_id = models.UUIDField()
    listing_title = models.CharField(max_length=255)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listing_transfers_sent"
    )
    source_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    source_agency = models.ForeignKey("agencies.Agency", null=True, on_delete=models.PROTECT, related_name="+")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="listing_transfers_received"
    )
    target_agency = models.ForeignKey(
        "agencies.Agency", null=True, on_delete=models.PROTECT, related_name="listing_transfers_received"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "listing_id"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_listing_transfer",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recipient__isnull=False, target_agency__isnull=True)
                    | models.Q(recipient__isnull=True, target_agency__isnull=False)
                ),
                name="listing_transfer_one_recipient",
            ),
        ]
