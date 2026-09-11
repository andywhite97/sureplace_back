from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


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
