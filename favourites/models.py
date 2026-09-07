import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Favourite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites")
    property = models.ForeignKey(
        "properties.PropertyListing", on_delete=models.CASCADE, null=True, blank=True, related_name="favourites"
    )
    stay = models.ForeignKey("stays.Stay", on_delete=models.CASCADE, null=True, blank=True, related_name="favourites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(property__isnull=False, stay__isnull=True)
                    | models.Q(property__isnull=True, stay__isnull=False)
                ),
                name="favourite_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["user", "property"],
                condition=models.Q(property__isnull=False),
                name="unique_user_property_favourite",
            ),
            models.UniqueConstraint(
                fields=["user", "stay"], condition=models.Q(stay__isnull=False), name="unique_user_stay_favourite"
            ),
        ]

    def clean(self):
        if bool(self.property_id) == bool(self.stay_id):
            raise ValidationError("Exactly one of property or stay must be set.")
