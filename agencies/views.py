from django.db import models, transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import EmailNotVerified, IsEmailVerified
from properties.models import ListingStatus, PropertyListing
from stays.models import Stay, StayStatus

from .models import Agency, AgencyInvitation, AgentProfile
from .permissions import AgencyPermissionDenied, active_profile, is_manager, is_owner
from .serializers import (
    AgencyInvitationSerializer,
    AgencySerializer,
    AgentProfileSerializer,
    InvitationActionSerializer,
    PublicAgentDetailSerializer,
    PublicAgentListSerializer,
    RoleUpdateSerializer,
)


class AgencyCreateEmailNotVerified(EmailNotVerified):
    default_detail = "Please verify your email address before creating an agency."


class PublicAgentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.AllowAny]
    serializer_class = PublicAgentListSerializer
    filter_backends = [SearchFilter]
    search_fields = [
        "user__first_name",
        "user__last_name",
        "bio",
        "agency__name",
        "agency__town",
        "agency__region",
    ]

    def get_queryset(self):
        queryset = (
            AgentProfile.objects.filter(is_active=True, user__is_active=True)
            .select_related("user", "agency")
            .prefetch_related("property_listings__images")
            .annotate(active_listing_count=Count("property_listings", filter=Q(property_listings__status="PUBLISHED")))
        )
        params = self.request.query_params
        verified_only = params.get("verified")
        if verified_only is not None and str(verified_only).lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(verification_status="VERIFIED")
        agency_id = params.get("agency")
        if agency_id:
            queryset = queryset.filter(agency_id=agency_id)
        region = params.get("region")
        if region:
            queryset = queryset.filter(Q(agency__region=region) | Q(property_listings__region=region))
        town = params.get("town")
        if town:
            queryset = queryset.filter(Q(agency__town=town) | Q(property_listings__town=town))
        ordering = params.get("ordering", "relevance")
        order_map = {
            "relevance": ["-verification_status", "-active_listing_count", "-created_at"],
            "name": ["user__first_name", "user__last_name"],
            "active": ["-active_listing_count", "-created_at"],
            "newest": ["-created_at", "-active_listing_count"],
        }
        queryset = queryset.order_by(*order_map.get(ordering, order_map["relevance"]))
        return queryset.distinct()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PublicAgentDetailSerializer
        return PublicAgentListSerializer


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current agency state."
    default_code = "conflict"


class AgencyViewSet(viewsets.ModelViewSet):
    serializer_class = AgencySerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agency_management"

    def get_queryset(self):
        return Agency.objects.filter(agents__user=self.request.user, agents__is_active=True).distinct()

    def get_object(self):
        obj = super().get_object()
        self.profile = active_profile(self.request.user, obj)
        if not self.profile:
            raise AgencyPermissionDenied()
        return obj

    def create(self, request, *args, **kwargs):
        if not request.user.is_email_verified:
            raise AgencyCreateEmailNotVerified()
        return super().create(request, *args, **kwargs)

    def perform_update(self, serializer):
        require_verified(self.request.user)
        agency = self.get_object()
        if not is_manager(active_profile(self.request.user, agency)):
            raise AgencyPermissionDenied()
        serializer.save()

    @action(detail=False, methods=["get"])
    def mine(self, request):
        qs = self.get_queryset().prefetch_related(
            models.Prefetch(
                "agents",
                queryset=AgentProfile.objects.filter(user=request.user, is_active=True),
                to_attr="_prefetched_agents",
            )
        )
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        agency = self.get_object()
        profile = active_profile(request.user, agency)
        properties = PropertyListing.objects.filter(agency=agency)
        stays = Stay.objects.filter(agency=agency)
        return Response(
            {
                "agency": AgencySerializer(agency, context=self.get_serializer_context()).data,
                "role": profile.role,
                "active_properties": properties.filter(status=ListingStatus.PUBLISHED).count(),
                "draft_properties": properties.filter(status=ListingStatus.DRAFT).count(),
                "active_stays": stays.filter(status=StayStatus.PUBLISHED).count(),
                "team_members": agency.agents.filter(is_active=True).count(),
                "pending_invitations": agency.invitations.filter(status=AgencyInvitation.Status.PENDING).count(),
                "verification_status": agency.verification_status,
            }
        )

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        agency = self.get_object()
        require_verified(request.user)
        if not is_manager(active_profile(request.user, agency)):
            raise AgencyPermissionDenied()
        return Response(
            AgentProfileSerializer(agency.agents.select_related("user").filter(is_active=True), many=True).data
        )

    @action(detail=True, methods=["get", "post"])
    def invitations(self, request, pk=None):
        agency = self.get_object()
        if not is_manager(active_profile(request.user, agency)):
            raise AgencyPermissionDenied()
        if request.method == "GET":
            return Response(AgencyInvitationSerializer(agency.invitations.all(), many=True).data)
        serializer = AgencyInvitationSerializer(data=request.data, context={"request": request, "agency": agency})
        serializer.is_valid(raise_exception=True)
        if agency.agents.filter(user__email__iexact=serializer.validated_data["email"], is_active=True).exists():
            raise Conflict("That user is already a member of this agency.")
        invitation = serializer.save()
        return Response(AgencyInvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="members/(?P<member_id>[^/.]+)/role")
    def update_member_role(self, request, pk=None, member_id=None):
        agency = self.get_object()
        require_verified(request.user)
        actor = active_profile(request.user, agency)
        if not is_owner(actor):
            raise AgencyPermissionDenied()
        serializer = RoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = agency.agents.get(pk=member_id, is_active=True)
        if is_owner(member) and serializer.validated_data["role"] != AgentProfile.Role.OWNER:
            ensure_other_owner(agency, member)
        member.role = serializer.validated_data["role"]
        member.save(update_fields=["role", "updated_at"])
        return Response(AgentProfileSerializer(member).data)

    @action(detail=True, methods=["delete"], url_path="members/(?P<member_id>[^/.]+)")
    def remove_member(self, request, pk=None, member_id=None):
        agency = self.get_object()
        require_verified(request.user)
        actor = active_profile(request.user, agency)
        if not is_owner(actor):
            raise AgencyPermissionDenied()
        member = agency.agents.get(pk=member_id, is_active=True)
        if is_owner(member):
            ensure_other_owner(agency, member)
        member.is_active = False
        member.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AgencyInvitationAcceptView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agency_invitation"

    def post(self, request):
        serializer = InvitationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = get_pending_invitation(serializer.validated_data["token"])
        if invitation.email.lower() != request.user.email.lower():
            raise AgencyPermissionDenied("This invitation was sent to a different email address.")
        with transaction.atomic():
            profile, _ = AgentProfile.objects.get_or_create(
                user=request.user, agency=invitation.agency, defaults={"role": invitation.role}
            )
            if not profile.is_active:
                profile.is_active = True
            profile.role = invitation.role
            profile.save(update_fields=["role", "is_active", "updated_at"])
            invitation.status = AgencyInvitation.Status.ACCEPTED
            invitation.accepted_by = request.user
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
        return Response(
            {
                "detail": "Invitation accepted.",
                "agency": AgencySerializer(invitation.agency, context={"request": request}).data,
            }
        )


class AgencyInvitationDeclineView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "agency_invitation"

    def post(self, request):
        serializer = InvitationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = get_pending_invitation(serializer.validated_data["token"])
        invitation.status = AgencyInvitation.Status.DECLINED
        invitation.declined_at = timezone.now()
        invitation.save(update_fields=["status", "declined_at", "updated_at"])
        return Response({"detail": "Invitation declined."})


def get_pending_invitation(token):
    invitation = AgencyInvitation.objects.select_related("agency", "inviter").filter(token=token).first()
    if not invitation or invitation.status != AgencyInvitation.Status.PENDING:
        raise ValidationError("Invitation is invalid or has already been used.")
    if invitation.is_expired:
        invitation.status = AgencyInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise ValidationError("Invitation has expired.")
    return invitation


def ensure_other_owner(agency, member):
    if not agency.agents.filter(role=AgentProfile.Role.OWNER, is_active=True).exclude(pk=member.pk).exists():
        raise Conflict("An agency must have at least one active owner.")


def require_verified(user):
    if not user.is_email_verified:
        raise EmailNotVerified()
