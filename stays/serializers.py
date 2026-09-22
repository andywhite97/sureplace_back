from django.conf import settings
from rest_framework import serializers
from .models import *
from .services import can_manage, quality


class ImageSerializer(serializers.ModelSerializer):

    class Meta:
        model = StayImage
        fields = ("id", "image", "caption", "sort_order", "is_cover", "created_at")


class RoomImageSerializer(serializers.ModelSerializer):

    def validate_image(self, value):
        if value.image.format not in ("JPEG", "PNG", "WEBP"):
            raise serializers.ValidationError("Unsupported image type. Choose JPG, PNG or WebP.")
        return value

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
        read_only_fields = ("slug",)

    def validate_room_choice(self, value, field, choices):
        # Free-text values saved by earlier clients remain editable without data loss.
        if not value or value in choices.values:
            return value
        labels = {label.casefold(): key for key, label in choices.choices}
        aliases = {"private": "PRIVATE", "shared": "SHARED", "en-suite": "ENSUITE", "queen and twin": "QUEEN_TWIN"}
        canonical = labels.get(value.casefold()) or aliases.get(value.casefold())
        if canonical in choices.values:
            return canonical
        if self.instance and value == getattr(self.instance, field):
            return value
        raise serializers.ValidationError("Select an available room option.")

    def validate_bed_configuration(self, value):
        return self.validate_room_choice(value, "bed_configuration", BedConfiguration)

    def validate_bathroom_type(self, value):
        return self.validate_room_choice(value, "bathroom_type", BathroomType)

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
    host = serializers.SerializerMethodField()

    class Meta:
        model = Stay
        exclude = ("location", "owner")

    def get_quality(self, o):
        return quality(o) if can_manage(self.context["request"].user, o) else None

    def get_room_types(self, o):
        return RoomSerializer(o.room_types.filter(is_active=True), many=True, context=self.context).data

    def get_verification_badges(self, o):
        return StayListSerializer().get_verification_badges(o)

    def get_host(self, o):
        request = self.context.get("request")

        def image_url(image):
            if not image:
                return None
            url = image.url
            return request.build_absolute_uri(url) if request else url

        owner_name = f"{o.owner.first_name} {o.owner.last_name}".strip() or "Stay owner"
        owner_avatar = image_url(o.owner.avatar)
        if o.agency:
            agent_name = None
            agent_avatar = None
            if o.agent:
                agent_name = f"{o.agent.user.first_name} {o.agent.user.last_name}".strip() or None
                agent_avatar = image_url(o.agent.user.avatar)
            return {
                "kind": "AGENCY",
                "name": o.agency.name,
                "role": "Hospitality agency",
                "image": image_url(o.agency.logo),
                "verification_status": o.agency.verification_status,
                "profile_slug": o.agency.slug,
                "representative_name": agent_name,
                "representative_image": agent_avatar,
            }
        if o.agent:
            agent_name = f"{o.agent.user.first_name} {o.agent.user.last_name}".strip() or "Stay agent"
            return {
                "kind": "AGENT",
                "name": agent_name,
                "role": "Stay agent",
                "image": image_url(o.agent.user.avatar),
                "verification_status": o.agent.verification_status,
                "profile_slug": None,
                "representative_name": None,
                "representative_image": None,
            }
        return {
            "kind": "OWNER",
            "name": owner_name,
            "role": "Stay owner",
            "image": owner_avatar,
            "verification_status": None,
            "profile_slug": None,
            "representative_name": None,
            "representative_image": None,
        }

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
        read_only_fields = (
            "public_id",
            "slug",
            "status",
            "verification_status",
            "featured",
            "published_at",
            "submitted_at",
        )

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
