from rest_framework import serializers
from .models import ListingReport


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingReport
        fields = "__all__"
        read_only_fields = ("reporter", "status", "assigned_to", "reviewed_at", "resolution_notes")

    def validate(self, a):
        if bool(a.get("property")) == bool(a.get("stay")):
            raise serializers.ValidationError("Exactly one listing target is required.")
        user = self.context["request"].user
        if ListingReport.objects.filter(
            reporter=user,
            property=a.get("property"),
            stay=a.get("stay"),
            reason=a.get("reason"),
            status__in=["OPEN", "UNDER_REVIEW"],
        ).exists():
            raise serializers.ValidationError("An identical open report already exists.")
        return a
