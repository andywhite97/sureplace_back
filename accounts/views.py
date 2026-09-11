from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
import logging
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView

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
)

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
