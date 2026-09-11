from rest_framework.exceptions import PermissionDenied

from .models import AgentProfile


class AgencyPermissionDenied(PermissionDenied):
    default_detail = "You do not have permission to manage this agency."
    default_code = "agency_permission_denied"


def active_profile(user, agency):
    if not user or not user.is_authenticated:
        return None
    return agency.agents.filter(user=user, is_active=True).first()


def is_owner(profile):
    return bool(profile and profile.role == AgentProfile.Role.OWNER)


def is_manager(profile):
    return bool(profile and profile.role in {AgentProfile.Role.OWNER, AgentProfile.Role.ADMIN})
