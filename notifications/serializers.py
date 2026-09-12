from urllib.parse import urlparse

from rest_framework import serializers
from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "notification_type",
            "title",
            "message",
            "data",
            "is_read",
            "read_at",
            "created_at",
            "expires_at",
            "action",
        )

    def get_action(self, obj):
        data = obj.data or {}
        route = self._semantic_listing_route(obj, data) or self._safe_route(data.get("route"))
        if not route:
            return None
        return {"label": self._action_label(obj, route), "url": route}

    def _semantic_listing_route(self, obj, data):
        action = str(data.get("action") or "").upper()
        status = str(data.get("status") or "").upper()
        property_slug = data.get("property_slug")
        property_id = data.get("property_id") or self._property_id_from_route(data.get("route"))

        if action in {"PROPERTY_APPROVED", "PROPERTY_RESTORED"} or status == "PUBLISHED":
            slug = property_slug or self._property_slug(property_id, obj.user_id)
            return f"/properties/{slug}" if slug else None
        if action in {
            "PROPERTY_SUBMITTED",
            "PROPERTY_CHANGES_REQUESTED",
            "PROPERTY_REJECTED",
            "PROPERTY_SUSPENDED",
        } or status in {"SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "REJECTED", "SUSPENDED"}:
            if property_id and self._property_exists(property_id, obj.user_id):
                return f"/account/manage/properties/{property_id}/edit"
            return "/account/manage/properties"
        return None

    def _property_slug(self, property_id, user_id):
        if not property_id:
            return ""
        try:
            from properties.models import PropertyListing

            return (
                PropertyListing.objects.filter(id=property_id, owner_id=user_id).values_list("slug", flat=True).first()
                or ""
            )
        except Exception:
            return ""

    def _property_exists(self, property_id, user_id):
        if not property_id:
            return False
        try:
            from properties.models import PropertyListing

            return PropertyListing.objects.filter(id=property_id, owner_id=user_id).exists()
        except Exception:
            return False

    def _property_id_from_route(self, route):
        route = self._safe_route(route)
        if not route:
            return ""
        prefix = "/account/manage/properties/"
        suffix = "/edit"
        if route.startswith(prefix) and route.endswith(suffix):
            return route[len(prefix) : -len(suffix)]
        return ""

    def _safe_route(self, route):
        if not isinstance(route, str) or not route.startswith("/") or route.startswith("//"):
            return ""
        parsed = urlparse(route)
        if parsed.scheme or parsed.netloc:
            return ""
        return route

    def _action_label(self, obj, route):
        data = obj.data or {}
        explicit = data.get("action_label")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        action = str(data.get("action") or "").upper()
        status = str(data.get("status") or "").upper()
        if action in {"PROPERTY_APPROVED", "PROPERTY_RESTORED"} or route.startswith("/properties/"):
            return "View listing"
        if action == "PROPERTY_CHANGES_REQUESTED" or status == "CHANGES_REQUESTED":
            return "Review changes"
        if action == "PROPERTY_REJECTED" or status == "REJECTED":
            return "View decision"
        return "Open"


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        exclude = ("user",)
