from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


STAFF_PERMISSION_CATALOG = (
    {
        "key": "properties.review_propertylisting",
        "label": "Review property listings",
        "description": "Open the listing queue and inspect listing details.",
    },
    {
        "key": "properties.approve_propertylisting",
        "label": "Approve property listings",
        "description": "Approve listings that meet SurePlace standards.",
    },
    {
        "key": "properties.request_changes_propertylisting",
        "label": "Request listing changes",
        "description": "Return listings to their owners with required corrections.",
    },
    {
        "key": "properties.reject_propertylisting",
        "label": "Reject property listings",
        "description": "Reject listings with a documented moderation reason.",
    },
    {
        "key": "properties.suspend_propertylisting",
        "label": "Suspend property listings",
        "description": "Temporarily remove published listings from the marketplace.",
    },
    {
        "key": "properties.restore_propertylisting",
        "label": "Restore property listings",
        "description": "Restore suspended listings after review.",
    },
    {
        "key": "properties.add_note_propertylisting",
        "label": "Add internal listing notes",
        "description": "Add staff-only notes to a listing moderation record.",
    },
    {
        "key": "verification.review_verificationrequest",
        "label": "Review verification requests",
        "description": "View protected verification evidence and make audited decisions.",
    },
    {
        "key": "accounts.moderate_user",
        "label": "Review and moderate user accounts",
        "description": "View the staff account-safety directory and restrict or reinstate accounts.",
    },
    {
        "key": "moderation.view_listingreport",
        "label": "View listing reports",
        "description": "Inspect reports submitted about marketplace listings.",
    },
    {
        "key": "moderation.add_listingreport",
        "label": "Resolve and dismiss listing reports",
        "description": "Record outcomes for listing reports.",
    },
)
STAFF_PERMISSION_KEYS = frozenset(item["key"] for item in STAFF_PERMISSION_CATALOG)


def effective_staff_permissions(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return []
    if user.is_superuser:
        return sorted(STAFF_PERMISSION_KEYS)
    return sorted(user.get_all_permissions().intersection(STAFF_PERMISSION_KEYS))


class EmailNotVerified(PermissionDenied):
    default_detail = "Please verify your email address to continue."
    default_code = "email_not_verified"


class IsEmailVerified(permissions.BasePermission):
    message = "Please verify your email address to continue."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if not request.user.is_email_verified:
            raise EmailNotVerified()
        return True
