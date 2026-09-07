from rest_framework import serializers
from properties.serializers import PropertyListSerializer
from stays.serializers import StayListSerializer
from .models import Favourite


class FavouriteSerializer(serializers.ModelSerializer):
    property_card = PropertyListSerializer(source="property", read_only=True)
    stay_card = StayListSerializer(source="stay", read_only=True)

    class Meta:
        model = Favourite
        fields = ("id", "property", "stay", "property_card", "stay_card", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, a):
        if bool(a.get("property")) == bool(a.get("stay")):
            raise serializers.ValidationError("Exactly one target is required.")
        user = self.context["request"].user
        if Favourite.objects.filter(user=user, property=a.get("property"), stay=a.get("stay")).exists():
            raise serializers.ValidationError("Already favourited.")
        return a

    def create(self, a):
        return Favourite.objects.create(user=self.context["request"].user, **a)
