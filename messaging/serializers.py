from rest_framework import serializers
from .models import *
from .services import create_conversation


class MessageSerializer(serializers.ModelSerializer):
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ("id", "sender", "message_type", "body", "created_at", "edited_at", "deleted_at", "is_mine")
        read_only_fields = ("sender", "created_at", "edited_at", "deleted_at")

    def get_is_mine(self, o):
        return o.sender_id == getattr(self.context.get("request"), "user", None).id

    def to_representation(self, o):
        d = super().to_representation(o)
        if o.deleted_at:
            d["body"] = "This message was deleted."
        return d


class ConversationSerializer(serializers.ModelSerializer):
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()
    context = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = (
            "id",
            "property",
            "stay",
            "subject",
            "status",
            "last_message_at",
            "last_message",
            "unread_count",
            "participants",
            "context",
            "created_at",
        )
        read_only_fields = ("status", "last_message_at", "created_at")

    def get_last_message(self, o):
        m = o.messages.last()
        return MessageSerializer(m, context=self.context).data if m else None

    def get_unread_count(self, o):
        user = getattr(self.context.get("request"), "user", None)
        participant = next((p for p in o.participants.all() if p.user_id == getattr(user, "id", None)), None)
        if not participant:
            return 0
        return sum(
            1 for message in o.messages.all()
            if message.sender_id != user.id and (not participant.last_read_at or message.created_at > participant.last_read_at)
        )

    def get_participants(self, o):
        user = getattr(self.context.get("request"), "user", None)
        return [
            {
                "id": str(p.id),
                "display_name": " ".join(filter(None, (p.user.first_name, p.user.last_name))) or "SurePlace member",
                "avatar": p.user.avatar.url if getattr(p.user, "avatar", None) else None,
                "participant_type": p.participant_type,
                "is_me": p.user_id == getattr(user, "id", None),
            }
            for p in o.participants.all() if p.is_active
        ]

    def get_context(self, o):
        listing = o.property or o.stay
        if not listing:
            return None
        if o.property_id:
            data = {
                "type": "PROPERTY", "id": str(listing.id), "slug": listing.slug,
                "title": listing.title, "town": listing.town, "suburb": listing.suburb,
                "image": listing.cover_image.image.url if listing.cover_image else None,
                "price": str(listing.price), "currency": listing.currency,
                "status": listing.availability_status,
            }
        else:
            data = {
            "type": "STAY", "id": str(listing.id), "slug": listing.slug,
            "title": listing.name, "town": listing.town, "suburb": listing.suburb,
            "image": listing.cover_image.image.url if listing.cover_image else None,
            "stay_type": listing.stay_type, "verification_status": listing.verification_status,
            }
        booking = o.bookings.select_related("room_type").order_by("-created_at").first()
        if booking:
            data["booking"] = {
                "id": str(booking.id), "reference": booking.reference, "room_name": booking.room_type.name,
                "check_in": str(booking.check_in), "check_out": str(booking.check_out),
                "status": booking.status, "total": str(booking.total), "currency": booking.currency,
            }
        viewing = o.viewing_requests.order_by("-created_at").first()
        if viewing:
            data["viewing"] = {
                "id": str(viewing.id), "requested_date": str(viewing.requested_date),
                "requested_time": str(viewing.requested_time), "status": viewing.status,
            }
        return data

    def create(self, a):
        return create_conversation(
            self.context["request"].user,
            self.context["request"].data.get("message", ""),
            a.get("property"),
            a.get("stay"),
            self.context["request"].data.get("message_type", MessageType.ENQUIRY),
        )


class GuestSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestEnquiry
        exclude = ("status", "converted_user", "converted_conversation")

    def validate(self, a):
        obj = GuestEnquiry(**a)
        try:
            obj.full_clean()
        except Exception as e:
            raise serializers.ValidationError(getattr(e, "message_dict", str(e)))
        return a
