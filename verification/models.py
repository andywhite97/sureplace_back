import uuid
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel
from .storage import private_verification_storage


class VerificationType(models.TextChoices):
    IDENTITY = "IDENTITY", "Identity"
    AGENT = "AGENT", "Agent"
    AGENCY = "AGENCY", "Agency"
    PROPERTY = "PROPERTY", "Property"
    STAY = "STAY", "Stay"
    BUSINESS = "BUSINESS", "Business"


class RequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


class VerificationRequest(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_requests"
    )
    verification_type = models.CharField(max_length=16, choices=VerificationType.choices)
    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, null=True, blank=True)
    agent_profile = models.ForeignKey("agencies.AgentProfile", on_delete=models.CASCADE, null=True, blank=True)
    property = models.ForeignKey("properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True)
    stay = models.ForeignKey("stays.Stay", on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=RequestStatus.choices, default=RequestStatus.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_verifications",
    )
    rejection_reason = models.TextField(blank=True)
    reviewer_notes = models.TextField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [("review_verificationrequest", "Can review verification requests")]
        indexes = [models.Index(fields=["status", "submitted_at"])]


class DocumentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"


class VerificationDocument(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification_request = models.ForeignKey(VerificationRequest, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=40)
    file = models.FileField(storage=private_verification_storage, upload_to="verification/%Y/%m/")
    status = models.CharField(max_length=10, choices=DocumentStatus.choices, default=DocumentStatus.PENDING)
    rejection_reason = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)


class VerificationAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification_request = models.ForeignKey(VerificationRequest, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    event_type = models.CharField(max_length=30)
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
