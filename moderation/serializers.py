from rest_framework import serializers

from properties.models import ListingStatus, PropertyListing
from properties.serializers import AgencySummarySerializer, PropertyImageSerializer
from .models import ListingReport, ModerationAuditEvent


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


class StaffUserSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone_number = serializers.CharField()
    is_email_verified = serializers.BooleanField()
    is_phone_verified = serializers.BooleanField()


class ModerationAuditEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = ModerationAuditEvent
        fields = ("id", "action", "reason", "metadata", "actor_name", "actor_email", "created_at")

    def get_actor_name(self, obj):
        if not obj.actor:
            return "System"
        return f"{obj.actor.first_name} {obj.actor.last_name}".strip() or obj.actor.email


class StaffListingReportSerializer(serializers.ModelSerializer):
    reporter_email = serializers.EmailField(source="reporter.email", read_only=True)

    class Meta:
        model = ListingReport
        fields = ("id", "reporter_email", "reason", "details", "status", "reviewed_at", "created_at")


class StaffPropertySerializer(serializers.ModelSerializer):
    owner = StaffUserSummarySerializer(read_only=True)
    agency = AgencySummarySerializer(read_only=True)
    images = PropertyImageSerializer(many=True, read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    open_reports_count = serializers.IntegerField(read_only=True)
    latest_note = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = PropertyListing
        fields = (
            "id",
            "public_id",
            "slug",
            "title",
            "description",
            "listing_type",
            "property_type",
            "price",
            "currency",
            "country_code",
            "region",
            "town",
            "suburb",
            "address",
            "latitude",
            "longitude",
            "bedrooms",
            "bathrooms",
            "parking_spaces",
            "floor_area",
            "land_area",
            "furnished",
            "pet_friendly",
            "status",
            "status_label",
            "verification_status",
            "availability_status",
            "availability_confirmed_at",
            "featured",
            "published_at",
            "expires_at",
            "owner",
            "agency",
            "images",
            "open_reports_count",
            "latest_note",
            "created_at",
            "updated_at",
        )

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_latest_note(self, obj):
        event = getattr(obj, "_latest_note", None)
        if event is None:
            event = obj.moderationauditevent_set.filter(action="PROPERTY_NOTE_ADDED").order_by("-created_at").first()
        return event.reason if event else ""


class StaffPropertyDetailSerializer(StaffPropertySerializer):
    reports = serializers.SerializerMethodField()
    audit_events = serializers.SerializerMethodField()

    class Meta(StaffPropertySerializer.Meta):
        fields = StaffPropertySerializer.Meta.fields + ("reports", "audit_events")

    def get_reports(self, obj):
        reports = obj.listingreport_set.select_related("reporter").order_by("-created_at")[:10]
        return StaffListingReportSerializer(reports, many=True, context=self.context).data

    def get_audit_events(self, obj):
        events = obj.moderationauditevent_set.select_related("actor").order_by("-created_at")[:25]
        return ModerationAuditEventSerializer(events, many=True, context=self.context).data


class StaffModerationActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    note = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        action = self.context.get("action")
        reason = attrs.get("reason", "").strip()
        note = attrs.get("note", "").strip()
        if action in {"request_changes", "reject", "suspend"} and not (reason or note):
            raise serializers.ValidationError({"reason": "A reason or note is required."})
        return attrs


STAFF_REVIEW_STATUSES = (
    ListingStatus.SUBMITTED,
    ListingStatus.UNDER_REVIEW,
    ListingStatus.CHANGES_REQUESTED,
    ListingStatus.REJECTED,
    ListingStatus.PUBLISHED,
    ListingStatus.SUSPENDED,
)
