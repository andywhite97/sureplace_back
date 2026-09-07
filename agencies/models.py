import uuid

from django.conf import settings
from django.db import models

from accounts.models import phone_validator
from core.choices import VerificationStatus
from core.models import TimeStampedModel


class Agency(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_profiles")
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="agents")
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
