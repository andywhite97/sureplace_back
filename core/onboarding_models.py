import uuid
from django.conf import settings
from django.db import models
from .models import TimeStampedModel


class OnboardingProspect(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "NEW"
        CONTENT_GATHERING = "CONTENT_GATHERING"
        PREVIEW_READY = "PREVIEW_READY"
        PREVIEW_SENT = "PREVIEW_SENT"
        CHANGES_REQUESTED = "CHANGES_REQUESTED"
        APPROVED = "APPROVED"
        CLAIM_PENDING = "CLAIM_PENDING"
        HANDED_OFF = "HANDED_OFF"
        CLOSED = "CLOSED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=8, choices=[("STAY", "Stay"), ("PROPERTY", "Property")], default="STAY")
    business_name = models.CharField(max_length=255)
    town = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.NEW)
    consent_status = models.CharField(
        max_length=16,
        choices=[
            ("UNKNOWN", "Unknown"),
            ("REQUESTED", "Requested"),
            ("GRANTED", "Granted"),
            ("WITHDRAWN", "Withdrawn"),
        ],
        default="UNKNOWN",
    )
    consent_evidence = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    next_action = models.CharField(max_length=500, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    draft_payload = models.JSONField(default=dict, blank=True)
    source_evidence = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    approved_version = models.PositiveIntegerField(null=True)
    approved_hash = models.CharField(max_length=64, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True)
    approval_evidence = models.TextField(blank=True)
    claim_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    claim_agency = models.ForeignKey("agencies.Agency", null=True, on_delete=models.SET_NULL, related_name="+")
    claim_expires_at = models.DateTimeField(null=True)
    resulting_stay = models.OneToOneField("stays.Stay", null=True, on_delete=models.SET_NULL, related_name="+")
    resulting_property = models.OneToOneField(
        "properties.PropertyListing", null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]
        permissions = [
            (f"{verb}_onboarding", label)
            for verb, label in [
                ("issue", "Issue private previews"),
                ("approve", "Record prospect approval"),
                ("handoff", "Invite verified prospect owners"),
            ]
        ]


class OnboardingPreview(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prospect = models.ForeignKey(OnboardingProspect, on_delete=models.CASCADE, related_name="previews")
    token_hash = models.CharField(max_length=64, unique=True)
    version = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)


class OnboardingImage(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prospect = models.ForeignKey(OnboardingProspect, on_delete=models.CASCADE, related_name="images")
    # Deliberately independent from public media storage/CDN. Small, bounded pilot images.
    content = models.BinaryField()
    caption = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=1000)
    permission_evidence = models.TextField()


class OnboardingAudit(models.Model):
    prospect = models.ForeignKey(OnboardingProspect, on_delete=models.CASCADE, related_name="audit")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=40)
    version = models.PositiveIntegerField()
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
