from django.contrib.auth import get_user_model
from rest_framework import serializers
from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from .models import OnboardingIntent

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "avatar",
            "is_email_verified",
            "is_phone_verified",
            "onboarding_intents",
            "date_joined",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "email",
            "is_email_verified",
            "is_phone_verified",
            "date_joined",
            "created_at",
            "updated_at",
        )


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    onboarding_intents = serializers.ListField(
        child=serializers.ChoiceField(choices=OnboardingIntent.choices),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "password",
            "onboarding_intents",
        )
        read_only_fields = ("id",)
        extra_kwargs = {"email": {"validators": []}}

    def validate_email(self, value):
        normalized_email = value.lower()
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized_email

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect."}, code="invalid_credentials"
            )
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        password_validation.validate_password(data["new_password"], user)
        return data


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(data["uid"])))
        except Exception:
            raise serializers.ValidationError("Invalid or expired reset link.", code="token_invalid")
        if not default_token_generator.check_token(user, data["token"]):
            raise serializers.ValidationError("Invalid or expired reset link.", code="token_invalid")
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        password_validation.validate_password(data["new_password"], user)
        data["user"] = user
        return data
