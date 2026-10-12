import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AuditedListingGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    agency = models.ForeignKey("agencies.Agency", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    grant_reason = models.TextField()
    granted_at = models.DateTimeField(default=timezone.now, editable=False)
    provider = models.CharField(max_length=80, blank=True)
    transaction_reference = models.CharField(max_length=160, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        if bool(self.account_id) == bool(self.agency_id):
            raise ValidationError("Select exactly one individual account or agency.")
        if not self.granted_by_id or not self.grant_reason.strip():
            raise ValidationError("Grants require an actor and a documented reason.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
