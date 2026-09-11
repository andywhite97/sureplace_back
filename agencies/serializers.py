from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from notifications.email_templates import absolute_url
from notifications.services import enqueue_transactional_email

from .models import Agency, AgencyInvitation, AgentProfile

User = get_user_model()


class AgencySerializer(serializers.ModelSerializer):
    user_role = serializers.SerializerMethodField()
    team_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Agency
        fields = (
            "id",
            "name",
            "trading_name",
            "slug",
            "logo",
            "description",
            "phone",
            "email",
            "whatsapp_number",
            "website",
            "address",
            "region",
            "town",
            "suburb",
            "country_code",
            "verification_status",
            "is_active",
            "user_role",
            "team_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "slug", "verification_status", "is_active", "user_role", "team_count")

    def get_user_role(self, obj):
        user = self.context.get("request").user if self.context.get("request") else None
        if not user or not user.is_authenticated:
            return ""
        profile = next((p for p in getattr(obj, "_prefetched_agents", []) if p.user_id == user.id), None)
        if profile:
            return profile.role
        return obj.agents.filter(user=user, is_active=True).values_list("role", flat=True).first() or ""

    def create(self, validated_data):
        request = self.context["request"]
        with transaction.atomic():
            agency = Agency.objects.create(slug=unique_slug(validated_data["name"]), **validated_data)
            AgentProfile.objects.create(user=request.user, agency=agency, role=AgentProfile.Role.OWNER)
        return agency


class AgentProfileSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    avatar = serializers.ImageField(source="user.avatar", read_only=True)

    class Meta:
        model = AgentProfile
        fields = (
            "id",
            "user",
            "name",
            "email",
            "avatar",
            "role",
            "bio",
            "professional_reference",
            "whatsapp_number",
            "verification_status",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "user", "name", "email", "avatar", "verification_status", "created_at")

    def get_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.email


class AgencyInvitationSerializer(serializers.ModelSerializer):
    inviter_name = serializers.SerializerMethodField()

    class Meta:
        model = AgencyInvitation
        fields = ("id", "agency", "email", "role", "status", "inviter_name", "expires_at", "created_at")
        read_only_fields = ("id", "agency", "status", "inviter_name", "expires_at", "created_at")

    def get_inviter_name(self, obj):
        return f"{obj.inviter.first_name} {obj.inviter.last_name}".strip() or obj.inviter.email

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()

    def create(self, validated_data):
        request = self.context["request"]
        agency = self.context["agency"]
        expires_at = timezone.now() + timedelta(days=getattr(settings, "AGENCY_INVITATION_TTL_DAYS", 7))
        invitation = AgencyInvitation.objects.create(
            agency=agency,
            inviter=request.user,
            email=validated_data["email"],
            role=validated_data["role"],
            expires_at=expires_at,
        )
        send_invitation_email(invitation)
        return invitation


class InvitationActionSerializer(serializers.Serializer):
    token = serializers.UUIDField()


class RoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=AgentProfile.Role.choices)


def unique_slug(name: str):
    base = slugify(name)[:220] or "agency"
    slug = base
    index = 2
    while Agency.objects.filter(slug=slug).exists():
        slug = f"{base}-{index}"
        index += 1
    return slug


def send_invitation_email(invitation: AgencyInvitation):
    route = f"agency-invitations/accept?token={invitation.token}"
    inviter_name = f"{invitation.inviter.first_name} {invitation.inviter.last_name}".strip() or invitation.inviter.email
    role_label = invitation.get_role_display()
    enqueue_transactional_email(
        invitation.email,
        f"You're invited to join {invitation.agency.name} on SurePlace",
        f"{inviter_name} invited you to join {invitation.agency.name} as {role_label}.",
        route,
        template_key="agency.invitation",
        tags={"category": "agency.invitation"},
        metadata={"agency_id": str(invitation.agency_id), "invitation_id": str(invitation.id)},
        context={
            "headline": f"Join {invitation.agency.name}",
            "cta_label": "Accept Invitation",
            "cta_url": absolute_url(route),
            "agency": {"name": invitation.agency.name},
            "inviter_name": inviter_name,
            "role": role_label,
            "expiry_text": f"This invitation expires on {invitation.expires_at:%d %b %Y}.",
        },
    )
