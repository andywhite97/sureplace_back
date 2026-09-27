from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.shortcuts import get_object_or_404
import logging
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView

from agencies.models import AgentProfile
from properties.models import PropertyListing
from stays.models import Stay

from .email_verification import (
    EmailVerificationError,
    EmailVerificationExpired,
    enqueue_verification_email,
    enqueue_verification_email_after_commit,
    enqueue_welcome_email_once,
    verify_email_token,
)
from .serializers import (
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegistrationSerializer,
    ResendVerificationSerializer,
    UserSerializer,
    StaffUserSerializer,
)
from .models import User, UserModerationEvent
from .permissions import STAFF_PERMISSION_CATALOG, STAFF_PERMISSION_KEYS

logger = logging.getLogger(__name__)


class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"


class RegisterView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    def perform_create(self, serializer):
        user = serializer.save()
        enqueue_verification_email_after_commit(user)

    def create(self, request, *args, **kwargs):
        if not settings.FEATURE_FLAGS["registration"]:
            return Response({"detail": "Registration is temporarily unavailable."}, status=503)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            self.perform_create(serializer)
        user = serializer.instance
        headers = self.get_success_headers(serializer.data)
        return Response(
            {
                "user": UserSerializer(user, context=self.get_serializer_context()).data,
                "email_verification_required": True,
                "detail": "Account created. Please verify your email.",
            },
            status=status.HTTP_201_CREATED,
            headers=headers,
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class CanModerateUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
            and (request.user.is_superuser or request.user.has_perm("accounts.moderate_user"))
        )


class StaffUserDirectoryView(generics.ListAPIView):
    """A read-only, permissioned directory for account-safety investigations."""

    serializer_class = StaffUserSerializer
    permission_classes = [CanModerateUser]
    filter_backends = [SearchFilter]
    search_fields = ["email", "first_name", "last_name"]

    def get_queryset(self):
        return UserSerializer.Meta.model.objects.order_by("-date_joined")


class StaffUserDetailView(generics.RetrieveAPIView):
    serializer_class = StaffUserSerializer
    permission_classes = [CanModerateUser]
    lookup_field = "pk"

    def get_queryset(self):
        return UserSerializer.Meta.model.objects.all()


class CanManageStaffAccess(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


STAFF_ROLE_PREFIX = "SurePlace / "


def _managed_roles():
    return Group.objects.filter(name__startswith=STAFF_ROLE_PREFIX).prefetch_related("permissions__content_type")


def _role_data(group):
    permission_keys = sorted(
        f"{item.content_type.app_label}.{item.codename}"
        for item in group.permissions.all()
        if f"{item.content_type.app_label}.{item.codename}" in STAFF_PERMISSION_KEYS
    )
    return {"id": group.pk, "name": group.name.removeprefix(STAFF_ROLE_PREFIX), "permissions": permission_keys}


def _resolve_role_permissions(keys):
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise ValidationError({"permissions": "Choose permissions from the provided list."})
    unknown = set(keys) - STAFF_PERMISSION_KEYS
    if unknown:
        raise ValidationError({"permissions": "One or more selected permissions are not assignable."})
    permissions_by_key = {
        f"{item.content_type.app_label}.{item.codename}": item
        for item in Permission.objects.select_related("content_type").filter(
            content_type__app_label__in={key.split(".", 1)[0] for key in keys},
            codename__in={key.split(".", 1)[1] for key in keys},
        )
    }
    if set(keys) - permissions_by_key.keys():
        raise ValidationError({"permissions": "A selected permission is not installed on this server."})
    return [permissions_by_key[key] for key in dict.fromkeys(keys)]


class StaffAccessView(APIView):
    permission_classes = [CanManageStaffAccess]

    def get(self, request):
        roles = list(_managed_roles())
        managed_ids = [role.id for role in roles]
        staff = User.objects.filter(is_staff=True, is_superuser=False).prefetch_related("groups").order_by("email")
        return Response(
            {
                "permissions": STAFF_PERMISSION_CATALOG,
                "roles": [_role_data(role) for role in roles],
                "staff": [
                    {
                        "id": str(user.id),
                        "name": f"{user.first_name} {user.last_name}".strip() or user.email,
                        "email": user.email,
                        "is_active": user.is_active,
                        "role_ids": sorted(group.id for group in user.groups.all() if group.id in managed_ids),
                    }
                    for user in staff
                ],
            }
        )

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        if not name or len(name) > 90 or name.startswith(STAFF_ROLE_PREFIX):
            raise ValidationError({"name": "Enter a role name between 1 and 90 characters."})
        full_name = f"{STAFF_ROLE_PREFIX}{name}"
        if Group.objects.filter(name__iexact=full_name).exists():
            raise ValidationError({"name": "A staff role with this name already exists."})
        permission_objects = _resolve_role_permissions(request.data.get("permissions", []))
        role = Group.objects.create(name=full_name)
        role.permissions.set(permission_objects)
        return Response(_role_data(role), status=status.HTTP_201_CREATED)


class StaffAccessRoleDetailView(APIView):
    permission_classes = [CanManageStaffAccess]

    def get_object(self, pk):
        from django.shortcuts import get_object_or_404

        return get_object_or_404(_managed_roles(), pk=pk)

    def patch(self, request, pk):
        role = self.get_object(pk)
        name = str(request.data.get("name", role.name.removeprefix(STAFF_ROLE_PREFIX))).strip()
        if not name or len(name) > 90 or name.startswith(STAFF_ROLE_PREFIX):
            raise ValidationError({"name": "Enter a role name between 1 and 90 characters."})
        full_name = f"{STAFF_ROLE_PREFIX}{name}"
        if Group.objects.filter(name__iexact=full_name).exclude(pk=role.pk).exists():
            raise ValidationError({"name": "A staff role with this name already exists."})
        permission_objects = _resolve_role_permissions(request.data.get("permissions", []))
        role.name = full_name
        role.save(update_fields=["name"])
        role.permissions.set(permission_objects)
        return Response(_role_data(role))

    def delete(self, request, pk):
        self.get_object(pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffUserRolesView(APIView):
    permission_classes = [CanManageStaffAccess]

    def put(self, request, pk):
        from django.shortcuts import get_object_or_404

        user = get_object_or_404(User, pk=pk, is_staff=True, is_superuser=False)
        role_ids = request.data.get("role_ids")
        if not isinstance(role_ids, list):
            raise ValidationError({"role_ids": "Provide a list of staff role IDs."})
        roles = list(_managed_roles().filter(pk__in=role_ids))
        if {role.pk for role in roles} != set(role_ids):
            raise ValidationError({"role_ids": "One or more selected roles are unavailable."})
        managed = Group.objects.filter(name__startswith=STAFF_ROLE_PREFIX)
        user.groups.remove(*managed.exclude(pk__in=role_ids))
        user.groups.add(*roles)
        return Response({"id": str(user.id), "role_ids": sorted(role.pk for role in roles)})


class StaffUserModerationActionView(APIView):
    permission_classes = [CanModerateUser]

    def post(self, request, pk, action):
        target = get_object_or_404(User, pk=pk)
        if target.pk == request.user.pk:
            raise ValidationError("You cannot moderate your own account.")
        if target.is_staff or target.is_superuser:
            raise ValidationError("Staff and superuser accounts cannot be moderated here.")
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise ValidationError({"reason": "A clear moderation reason is required."})
        if action == "restrict":
            if not target.is_active:
                raise ValidationError("This account is already restricted.")
            target.is_active = False
            event_action = UserModerationEvent.Action.RESTRICTED
        elif action == "reinstate":
            if target.is_active:
                raise ValidationError("This account is already active.")
            target.is_active = True
            event_action = UserModerationEvent.Action.REINSTATED
        else:
            raise ValidationError("Unknown moderation action.")

        with transaction.atomic():
            target.save(update_fields=["is_active", "updated_at"])
            UserModerationEvent.objects.create(
                user=target,
                actor=request.user,
                action=event_action,
                reason=reason,
            )
            from notifications.models import NotificationType
            from notifications.services import create_notification

            create_notification(
                target,
                NotificationType.SYSTEM,
                "Account access updated",
                "Your SurePlace account access has been updated. Contact support if you need help.",
                {"route": "/help"},
                f"account-moderation:{event_action}:{target.id}",
            )
        return Response(StaffUserSerializer(target).data)


class CapabilitySummaryView(APIView):
    """Relationship facts for frontend personalization; endpoint permissions remain authoritative."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        memberships = AgentProfile.objects.filter(user=request.user, is_active=True)
        roles = list(memberships.values_list("role", flat=True))
        return Response(
            {
                "has_individual_property_context": PropertyListing.objects.filter(
                    owner=request.user, agency__isnull=True
                ).exists(),
                "has_individual_stay_context": Stay.objects.filter(owner=request.user, agency__isnull=True).exists(),
                "has_agent_profile": bool(roles),
                "has_agency_management_context": bool(roles),
                "can_manage_agency": any(role in {AgentProfile.Role.OWNER, AgentProfile.Role.ADMIN} for role in roles),
                "agency_count": len(roles),
            }
        )


class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification"

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = verify_email_token(serializer.validated_data["token"])
        except EmailVerificationExpired:
            return Response({"detail": "Verification link expired.", "code": "token_expired"}, status=410)
        except EmailVerificationError:
            return Response({"detail": "Verification link is invalid.", "code": "token_invalid"}, status=400)
        if user.is_email_verified:
            return Response({"detail": "Email is already verified.", "email_verified": True})
        user.is_email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=["is_email_verified", "email_verified_at", "updated_at"])

        def send_welcome():
            try:
                enqueue_welcome_email_once(user)
            except Exception:
                logger.exception("welcome_email_enqueue_failed user_id=%s", user.id)

        transaction.on_commit(send_welcome)
        return Response({"detail": "Email verified successfully.", "email_verified": True})


class ResendVerificationView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification"

    detail = "If that address belongs to an unverified account, a verification email has been sent."

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from django.contrib.auth import get_user_model

        user = (
            get_user_model()
            .objects.filter(email__iexact=serializer.validated_data["email"], is_active=True, is_email_verified=False)
            .first()
        )
        if user:
            try:
                enqueue_verification_email(user)
            except Exception:
                logger.exception("email_verification_resend_failed user_id=%s", user.id)
        return Response({"detail": self.detail})


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            RefreshToken(request.data.get("refresh", "")).blacklist()
        except TokenError:
            return Response({"detail": "Invalid refresh token."}, status=400)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password changed."})


class PasswordResetView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = (
            __import__("django.contrib.auth", fromlist=["get_user_model"])
            .get_user_model()
            .objects.filter(email__iexact=serializer.validated_data["email"], is_active=True)
            .first()
        )
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_route = f"reset-password?uid={uid}&token={token}"
            link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/{reset_route}"
            from notifications.services import enqueue_transactional_email

            transaction.on_commit(
                lambda: enqueue_transactional_email(
                    user.email,
                    "Reset your SurePlace password",
                    f"Use this link to reset your password: {link}",
                    reset_route,
                    template_key="auth.password_reset",
                    tags={"category": "auth.password_reset"},
                    context={
                        "cta_url": link,
                        "expiry_text": "For your security, this reset link will expire after a limited time.",
                    },
                )
            )
        return Response({"detail": "If an account exists for this email, reset instructions have been sent."})


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password reset complete."})
