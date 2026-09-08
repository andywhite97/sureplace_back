from datetime import datetime
from django.utils import timezone
from rest_framework import serializers
from .models import Booking, ViewingRequest


class ViewingSerializer(serializers.ModelSerializer):
    requester_display_name = serializers.SerializerMethodField()
    property_title = serializers.CharField(source="property.title", read_only=True)
    property_slug = serializers.CharField(source="property.slug", read_only=True)
    property_town = serializers.CharField(source="property.town", read_only=True)
    property_suburb = serializers.CharField(source="property.suburb", read_only=True)
    property_image = serializers.SerializerMethodField()

    class Meta:
        model = ViewingRequest
        fields = "__all__"
        read_only_fields = (
            "requester",
            "agent",
            "conversation",
            "status",
            "confirmed_at",
            "cancelled_at",
            "completed_at",
        )

    def validate(self, a):
        when = timezone.make_aware(datetime.combine(a["requested_date"], a["requested_time"]))
        if when <= timezone.now():
            raise serializers.ValidationError("Viewing must be in the future.")
        return a

    def get_property_image(self, obj):
        return obj.property.cover_image.image.url if obj.property.cover_image else None

    def get_requester_display_name(self, obj):
        return " ".join(filter(None, (obj.requester.first_name, obj.requester.last_name))) or "SurePlace member"


class BookingSerializer(serializers.ModelSerializer):
    stay_name = serializers.CharField(source="stay.name", read_only=True)
    stay_slug = serializers.CharField(source="stay.slug", read_only=True)
    stay_town = serializers.CharField(source="stay.town", read_only=True)
    stay_suburb = serializers.CharField(source="stay.suburb", read_only=True)
    stay_image = serializers.SerializerMethodField()
    room_name = serializers.CharField(source="room_type.name", read_only=True)

    class Meta:
        model = Booking
        fields = "__all__"
        read_only_fields = (
            "reference",
            "stay",
            "guest",
            "conversation",
            "nightly_pricing",
            "nightly_subtotal",
            "taxes",
            "fees",
            "total",
            "currency",
            "status",
            "payment_status",
            "expires_at",
            "confirmed_at",
            "cancelled_at",
            "completed_at",
        )

    def get_stay_image(self, obj):
        return obj.stay.cover_image.image.url if obj.stay.cover_image else None
