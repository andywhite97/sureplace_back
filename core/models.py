from django.db import models


class TimeStampedModel(models.Model):
    """Common audit timestamps for domain models."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
