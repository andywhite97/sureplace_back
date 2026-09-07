import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.models import TimeStampedModel


class ConversationStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    ACTIVE = "ACTIVE", "Active"
    CLOSED = "CLOSED", "Closed"
    ARCHIVED = "ARCHIVED", "Archived"
    BLOCKED = "BLOCKED", "Blocked"


class ParticipantType(models.TextChoices):
    SEEKER = "SEEKER", "Seeker"
    OWNER = "OWNER", "Owner"
    AGENT = "AGENT", "Agent"
    AGENCY_STAFF = "AGENCY_STAFF", "Agency staff"
    HOST = "HOST", "Host"
    SYSTEM = "SYSTEM", "System"


class MessageType(models.TextChoices):
    TEXT = "TEXT", "Text"
    SYSTEM = "SYSTEM", "System"
    VIEWING_REQUEST = "VIEWING_REQUEST", "Viewing request"
    VIEWING_UPDATE = "VIEWING_UPDATE", "Viewing update"
    ENQUIRY = "ENQUIRY", "Enquiry"
    BOOKING_ENQUIRY = "BOOKING_ENQUIRY", "Booking enquiry"


class Conversation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(
        "properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True, related_name="conversations"
    )
    stay = models.ForeignKey(
        "stays.Stay", on_delete=models.CASCADE, null=True, blank=True, related_name="conversations"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_conversations"
    )
    assigned_agent = models.ForeignKey(
        "agencies.AgentProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations"
    )
    status = models.CharField(max_length=10, choices=ConversationStatus.choices, default=ConversationStatus.OPEN)
    subject = models.CharField(max_length=255, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [models.Index(fields=["-last_message_at"])]

    def clean(self):
        if bool(self.property_id) == bool(self.stay_id):
            raise ValidationError("Marketplace conversations require exactly one listing target.")


class ConversationParticipant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_participations"
    )
    participant_type = models.CharField(max_length=20, choices=ParticipantType.choices)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="unique_conversation_participant")]


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="sent_messages"
    )
    message_type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.TEXT)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]


class GuestEnquiryStatus(models.TextChoices):
    NEW = "NEW", "New"
    CONTACTED = "CONTACTED", "Contacted"
    CONVERTED = "CONVERTED", "Converted"
    CLOSED = "CLOSED", "Closed"
    SPAM = "SPAM", "Spam"


class GuestEnquiry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    property = models.ForeignKey(
        "properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True, related_name="guest_enquiries"
    )
    stay = models.ForeignKey(
        "stays.Stay", on_delete=models.CASCADE, null=True, blank=True, related_name="guest_enquiries"
    )
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=16, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=GuestEnquiryStatus.choices, default=GuestEnquiryStatus.NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    converted_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    converted_conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)

    def clean(self):
        if bool(self.property_id) == bool(self.stay_id):
            raise ValidationError("Exactly one target is required.")
        if not self.email and not self.phone_number:
            raise ValidationError("Email or phone is required.")


class ConversationReport(TimeStampedModel):
    class Reason(models.TextChoices):
        SPAM = "SPAM", "Spam"
        SCAM = "SCAM", "Scam"
        HARASSMENT = "HARASSMENT", "Harassment"
        INAPPROPRIATE = "INAPPROPRIATE", "Inappropriate"
        OTHER = "OTHER", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="OPEN")
