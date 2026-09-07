from datetime import datetime
from django.utils import timezone
from rest_framework import serializers
from .models import Booking, ViewingRequest


class ViewingSerializer(serializers.ModelSerializer):
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


class BookingSerializer(serializers.ModelSerializer):
    stay_name = serializers.CharField(source="stay.name", read_only=True)
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
