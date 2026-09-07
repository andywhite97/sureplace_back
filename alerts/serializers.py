from rest_framework import serializers
from .criteria import validate_criteria
from .models import Frequency, SavedSearch


class SavedSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedSearch
        exclude = ("user",)
        read_only_fields = ("last_checked_at", "last_notified_at", "created_at", "updated_at")

    def validate(self, a):
        search_type = a.get("search_type", getattr(self.instance, "search_type", None))
        a["criteria"] = validate_criteria(search_type, a.get("criteria", getattr(self.instance, "criteria", {})))
        frequency = a.get("frequency", getattr(self.instance, "frequency", Frequency.DAILY))
        if frequency == Frequency.OFF:
            a["notifications_enabled"] = False
        return a

    def create(self, a):
        if not a.get("name"):
            c = a["criteria"]
            label = c.get("town") or c.get("region") or "Eswatini"
            a["name"] = (c.get("property_type") or c.get("stay_type") or a["search_type"].title()).replace(
                "_", " "
            ).title() + f" in {label}"
        return SavedSearch.objects.create(user=self.context["request"].user, **a)
