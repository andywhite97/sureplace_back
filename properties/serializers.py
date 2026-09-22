from django.conf import settings
from rest_framework import serializers

from agencies.models import AgentProfile
from .models import Amenity, PropertyImage, PropertyListing
from .permissions import can_manage_property
from .services import listing_quality


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ("id", "name", "slug", "icon", "category")


class AbsoluteImageField(serializers.ImageField):
    def to_representation(self, value):
        url = super().to_representation(value)
        request = self.context.get("request")
        if url and request and not str(url).startswith(("http://", "https://")):
            return request.build_absolute_uri(url)
        return url


class PropertyImageSerializer(serializers.ModelSerializer):
    image = AbsoluteImageField()

    class Meta:
        model = PropertyImage
        fields = ("id", "image", "caption", "sort_order", "is_cover", "created_at")


class AgencySummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    logo = serializers.ImageField()
    verification_status = serializers.CharField()


class AgentSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.SerializerMethodField()
    whatsapp_number = serializers.CharField()
    verification_status = serializers.CharField()

    def get_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


class LocationMixin:
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)


class PropertyListSerializer(LocationMixin, serializers.ModelSerializer):
    verification_badges = serializers.SerializerMethodField()
    is_favourited = serializers.BooleanField(source="_is_favourited", read_only=True, default=False)
    cover_image = serializers.SerializerMethodField()
    agency = AgencySummarySerializer(read_only=True)
    agent = AgentSummarySerializer(read_only=True)

    class Meta:
        model = PropertyListing
        fields = (
            "id",
            "public_id",
            "slug",
            "title",
            "listing_type",
            "property_type",
            "price",
            "currency",
            "town",
            "suburb",
            "region",
            "latitude",
            "longitude",
            "bedrooms",
            "bathrooms",
            "parking_spaces",
            "floor_area",
            "land_area",
            "featured",
            "verification_status",
            "verification_badges",
            "availability_status",
            "availability_confirmed_at",
            "cover_image",
            "agent",
            "agency",
            "is_favourited",
            "created_at",
        )

    def get_cover_image(self, obj):
        prefetched = getattr(obj, "_cover_images", None)
        image = prefetched[0] if prefetched else None
        if prefetched is None:
            image = obj.cover_image
        if not image:
            return None
        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url

    def get_verification_badges(self, obj):
        badges = []
        if obj.verification_status == "VERIFIED":
            badges.append({"type": "PROPERTY", "label": "Verified Property"})
        if obj.agent and obj.agent.verification_status == "VERIFIED":
            badges.append({"type": "AGENT", "label": "Verified Agent"})
        if obj.agency and obj.agency.verification_status == "VERIFIED":
            badges.append({"type": "AGENCY", "label": "Verified Agency"})
        return badges


class PropertyDetailSerializer(LocationMixin, serializers.ModelSerializer):
    verification_badges = serializers.SerializerMethodField()
    is_favourited = serializers.BooleanField(source="_is_favourited", read_only=True, default=False)
    images = PropertyImageSerializer(many=True, read_only=True)
    amenities = AmenitySerializer(many=True, read_only=True)
    agency = AgencySummarySerializer(read_only=True)
    agent = AgentSummarySerializer(read_only=True)
    advertiser = serializers.SerializerMethodField()
    quality = serializers.SerializerMethodField()

    class Meta:
        model = PropertyListing
        exclude = ("location", "owner")

    def get_quality(self, obj):
        request = self.context.get("request")
        return listing_quality(obj) if request and can_manage_property(request.user, obj) else None

    def get_verification_badges(self, obj):
        return PropertyListSerializer(context=self.context).get_verification_badges(obj)

    def get_advertiser(self, obj):
        request = self.context.get("request")

        def image_url(image):
            if not image:
                return None
            url = image.url
            return request.build_absolute_uri(url) if request else url

        owner_name = f"{obj.owner.first_name} {obj.owner.last_name}".strip() or "Property owner"
        if obj.agency:
            representative_name = None
            representative_image = None
            if obj.agent:
                representative_name = f"{obj.agent.user.first_name} {obj.agent.user.last_name}".strip() or None
                representative_image = image_url(obj.agent.user.avatar)
            return {
                "kind": "AGENCY",
                "name": obj.agency.name,
                "role": "Real estate agency",
                "image": image_url(obj.agency.logo),
                "verification_status": obj.agency.verification_status,
                "profile_slug": obj.agency.slug,
                "representative_name": representative_name,
                "representative_image": representative_image,
            }
        if obj.agent:
            agent_name = f"{obj.agent.user.first_name} {obj.agent.user.last_name}".strip() or "Property agent"
            return {
                "kind": "AGENT",
                "name": agent_name,
                "role": "Property agent",
                "image": image_url(obj.agent.user.avatar),
                "verification_status": obj.agent.verification_status,
                "profile_slug": None,
                "representative_name": None,
                "representative_image": None,
            }
        return {
            "kind": "OWNER",
            "name": owner_name,
            "role": "Property owner",
            "image": image_url(obj.owner.avatar),
            "verification_status": None,
            "profile_slug": None,
            "representative_name": None,
            "representative_image": None,
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["latitude"] = instance.latitude
        data["longitude"] = instance.longitude
        if data["quality"] is None:
            data.pop("quality")
        return data


class PropertyWriteSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(write_only=True, required=False, min_value=-90, max_value=90)
    longitude = serializers.FloatField(write_only=True, required=False, min_value=-180, max_value=180)
    amenities = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Amenity.objects.filter(is_active=True), required=False
    )

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
            "amenities",
            "agency",
            "agent",
            "status",
            "verification_status",
            "availability_status",
            "availability_confirmed_at",
            "featured",
            "published_at",
            "expires_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "public_id",
            "slug",
            "status",
            "verification_status",
            "availability_status",
            "availability_confirmed_at",
            "featured",
            "published_at",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        latitude = attrs.pop("latitude", None)
        longitude = attrs.pop("longitude", None)
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError("Latitude and longitude must be supplied together.")
        if latitude is not None:
            if settings.USE_SQLITE:
                attrs["location"] = {"latitude": latitude, "longitude": longitude}
            else:
                from django.contrib.gis.geos import Point

                attrs["location"] = Point(longitude, latitude, srid=4326)

        request = self.context["request"]
        agency = attrs.get("agency", getattr(self.instance, "agency", None))
        agent = attrs.get("agent", getattr(self.instance, "agent", None))
        if agent and agency and agent.agency_id != agency.id:
            raise serializers.ValidationError({"agent": "Agent must belong to the selected agency."})
        if agent and not agency:
            attrs["agency"] = agent.agency
            agency = agent.agency
        if (agency or agent) and not request.user.is_staff:
            permitted = AgentProfile.objects.filter(user=request.user, agency=agency, is_active=True).exists()
            if not permitted:
                raise serializers.ValidationError({"agency": "You must be active staff of this agency."})

        instance = self.instance or PropertyListing(owner=request.user)
        for key, value in attrs.items():
            if key != "amenities":
                setattr(instance, key, value)
        try:
            instance.full_clean(exclude=["public_id", "slug"])
        except Exception as exc:
            if hasattr(exc, "message_dict"):
                raise serializers.ValidationError(exc.message_dict) from exc
            raise
        return attrs

    def create(self, validated_data):
        amenities = validated_data.pop("amenities", [])
        listing = PropertyListing.objects.create(owner=self.context["request"].user, **validated_data)
        listing.amenities.set(amenities)
        return listing

    def update(self, instance, validated_data):
        amenities = validated_data.pop("amenities", None)
        instance = super().update(instance, validated_data)
        if amenities is not None:
            instance.amenities.set(amenities)
        return instance
