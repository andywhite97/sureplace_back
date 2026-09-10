from django.conf import settings
from rest_framework import serializers
from .models import *
from .services import can_manage, quality


class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = StayImage
        fields = ("id", "image", "caption", "sort_order", "is_cover", "created_at")


class RoomImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomTypeImage
        fields = ("id", "image", "caption", "sort_order", "is_cover", "created_at")


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = StayAmenity
        fields = ("id", "name", "slug", "icon", "category")


class RoomSerializer(serializers.ModelSerializer):
    images = RoomImageSerializer(many=True, read_only=True)

    class Meta:
        model = RoomType
        fields = "__all__"
        read_only_fields = ("stay",)


class RoomWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        exclude = ("stay",)

    def validate(self, attrs):
        obj = self.instance or RoomType(stay=self.context["stay"])
        for k, v in attrs.items():
            setattr(obj, k, v)
        try:
            obj.full_clean(exclude=["slug"])
        except Exception as e:
            raise serializers.ValidationError(getattr(e, "message_dict", str(e)))
        return attrs


class StayListSerializer(serializers.ModelSerializer):
    verification_badges = serializers.SerializerMethodField()
    is_favourited = serializers.BooleanField(source="_is_favourited", read_only=True, default=False)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    cover_image = serializers.SerializerMethodField()
    minimum_nightly_price = serializers.SerializerMethodField()
    available_room_type_count = serializers.SerializerMethodField()

    class Meta:
        model = Stay
        fields = (
            "id",
            "public_id",
            "slug",
            "name",
            "stay_type",
            "region",
            "town",
            "suburb",
            "latitude",
            "longitude",
            "verification_status",
            "verification_badges",
            "featured",
            "cover_image",
            "minimum_nightly_price",
            "available_room_type_count",
            "is_favourited",
            "created_at",
        )

    def get_verification_badges(self, o):
        return (
            ([{"type": "STAY", "label": "Verified Stay"}] if o.verification_status == "VERIFIED" else [])
            + (
                [{"type": "AGENT", "label": "Verified Agent"}]
                if o.agent and o.agent.verification_status == "VERIFIED"
                else []
            )
            + (
                [{"type": "AGENCY", "label": "Verified Agency"}]
                if o.agency and o.agency.verification_status == "VERIFIED"
                else []
            )
        )

    def get_cover_image(self, o):
        prefetched = getattr(o, "_cover_images", None)
        image = prefetched[0] if prefetched else None
        if prefetched is None:
            image = o.cover_image
        return image.image.url if image else None

    def get_minimum_nightly_price(self, o):
        value = getattr(o, "_minimum_nightly_price", None)
        if value is not None:
            return str(value)
        room = o.room_types.filter(is_active=True).order_by("base_price").first()
        return str(room.base_price) if room else None

    def get_available_room_type_count(self, o):
        value = getattr(o, "_available_room_type_count", None)
        if value is not None:
            return value
        return o.room_types.filter(is_active=True, quantity__gt=0).count()


class StayDetailSerializer(serializers.ModelSerializer):
    verification_badges = serializers.SerializerMethodField()
    is_favourited = serializers.BooleanField(source="_is_favourited", read_only=True, default=False)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    images = ImageSerializer(many=True, read_only=True)
    amenities = AmenitySerializer(many=True, read_only=True)
    room_types = serializers.SerializerMethodField()
    quality = serializers.SerializerMethodField()

    class Meta:
        model = Stay
        exclude = ("location", "owner")

    def get_quality(self, o):
        return quality(o) if can_manage(self.context["request"].user, o) else None

    def get_room_types(self, o):
        return RoomSerializer(o.room_types.filter(is_active=True), many=True).data

    def get_verification_badges(self, o):
        return StayListSerializer().get_verification_badges(o)

    def to_representation(self, o):
        data = super().to_representation(o)
        if data["quality"] is None:
            data.pop("quality")
        return data


class StayWriteSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)
    amenities = serializers.PrimaryKeyRelatedField(
        many=True, queryset=StayAmenity.objects.filter(is_active=True), required=False
    )

    class Meta:
        model = Stay
        exclude = ("owner", "location")
        read_only_fields = ("public_id", "slug", "status", "verification_status", "featured", "published_at")

    def validate(self, a):
        lat = a.pop("latitude", None)
        lon = a.pop("longitude", None)
        if (lat is None) != (lon is None):
            raise serializers.ValidationError("Latitude and longitude are required together.")
        if lat is not None:
            if settings.USE_SQLITE:
                a["location"] = {"latitude": lat, "longitude": lon}
            else:
                from django.contrib.gis.geos import Point

                a["location"] = Point(lon, lat, srid=4326)
        agency = a.get("agency", getattr(self.instance, "agency", None))
        agent = a.get("agent", getattr(self.instance, "agent", None))
        user = self.context["request"].user
        if agent and agency and agent.agency_id != agency.id:
            raise serializers.ValidationError({"agent": "Agent must belong to the agency."})
        if agent and not agency:
            a["agency"] = agent.agency
            agency = agent.agency
        if agency and not user.is_staff and not user.agent_profiles.filter(agency=agency, is_active=True).exists():
            raise serializers.ValidationError({"agency": "You must be active staff of this agency."})
        return a

    def create(self, a):
        amenities = a.pop("amenities", [])
        obj = Stay.objects.create(owner=self.context["request"].user, **a)
        obj.amenities.set(amenities)
        return obj


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomAvailability
        exclude = ("room_type",)

    def validate(self, a):
        obj = self.instance or RoomAvailability(room_type=self.context["room"])
        for k, v in a.items():
            setattr(obj, k, v)
        try:
            obj.full_clean()
        except Exception as e:
            raise serializers.ValidationError(getattr(e, "message_dict", str(e)))
        return a
