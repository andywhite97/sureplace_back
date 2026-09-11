from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    ChangePasswordSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    RegistrationSerializer,
    UserSerializer,
)


class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"


class RegisterView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    def create(self, request, *args, **kwargs):
        if not settings.FEATURE_FLAGS["registration"]:
            return Response({"detail": "Registration is temporarily unavailable."}, status=503)
        with transaction.atomic():
            return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = serializer.save()
        from notifications.services import enqueue_transactional_email

        transaction.on_commit(
            lambda: enqueue_transactional_email(
                user.email,
                "Welcome to SurePlace",
                (
                    "Your account is ready. You can now explore properties, save favourites, "
                    "request viewings, book stays, and message hosts or agents."
                ),
                "/properties",
                template_key="auth.welcome",
                tags={"category": "auth.welcome"},
            )
        )


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


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
