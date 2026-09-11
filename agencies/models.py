import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import phone_validator
from core.choices import VerificationStatus
from core.models import TimeStampedModel


class Agency(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    trading_name = models.CharField(max_length=255, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    logo = models.ImageField(upload_to="sureplace/agencies/logos/", blank=True, null=True)
    description = models.TextField(blank=True)
    phone = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    whatsapp_number = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    country_code = models.CharField(max_length=2, default="SZ")
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "agencies"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AgentProfile(TimeStampedModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ADMIN = "ADMIN", "Admin"
        AGENT = "AGENT", "Agent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_profiles")
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="agents")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.AGENT)
    bio = models.TextField(blank=True)
    professional_reference = models.CharField(max_length=255, blank=True)
    whatsapp_number = models.CharField(max_length=16, blank=True, validators=[phone_validator])
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "agency"], name="unique_user_agency_profile")]
        ordering = ["agency__name", "user__email"]

    def __str__(self):
        return f"{self.user.email} at {self.agency.name}"


class AgencyInvitation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=AgentProfile.Role.choices, default=AgentProfile.Role.AGENT)
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agency_invitations_sent"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="agency_invitations_accepted",
    )
    accepted_at = models.DateTimeField(blank=True, null=True)
    declined_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["agency", "email", "status"],
                condition=models.Q(status="PENDING"),
                name="unique_pending_agency_invitation",
            )
        ]

    def __str__(self):
        return f"{self.email} -> {self.agency.name}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at
