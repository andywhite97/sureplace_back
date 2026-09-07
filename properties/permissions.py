from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import ListingStatus


def can_manage_property(user, listing):
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or listing.owner_id == user.id:
        return True
    if listing.agent_id and listing.agent.user_id == user.id and listing.agent.is_active:
        return True
    if listing.agency_id:
        return user.agent_profiles.filter(agency_id=listing.agency_id, is_active=True).exists()
    return False


class PropertyPermission(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS and obj.status == ListingStatus.PUBLISHED:
            return True
        return can_manage_property(request.user, obj)
