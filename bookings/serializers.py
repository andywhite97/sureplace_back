from datetime import datetime
from django.utils import timezone
from rest_framework import serializers
from .models import Booking, ViewingRequest


class BookingCreateSerializer(serializers.Serializer):
    room_type = serializers.UUIDField()
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    adults = serializers.IntegerField(min_value=1, max_value=32767, default=1)
    children = serializers.IntegerField(min_value=0, max_value=32767, default=0)
    rooms = serializers.IntegerField(min_value=1, max_value=32767, default=1)
    guest_name = serializers.CharField(max_length=200)
    guest_email = serializers.EmailField(max_length=254)
    guest_phone = serializers.CharField(max_length=20, allow_blank=True, default="")
    special_requests = serializers.CharField(max_length=1000, allow_blank=True, default="")
    expected_total = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    policies_accepted = serializers.BooleanField(required=True)


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
    stay_latitude = serializers.FloatField(source="stay.latitude", read_only=True)
    stay_longitude = serializers.FloatField(source="stay.longitude", read_only=True)

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
