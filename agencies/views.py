import math

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
from bookings.models import Booking, BookingStatus, ViewingRequest, ViewingStatus
from messaging.models import GuestEnquiry

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


class ManagementDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        agencies = self._agencies(request)
        individual_properties = PropertyListing.objects.filter(owner=request.user, agency__isnull=True)
        individual_stays = Stay.objects.filter(owner=request.user, agency__isnull=True)
        individual_intents = {"PROPERTY_OWNER", "HOSPITALITY_OPERATOR"}
        has_individual = (
            individual_properties.exists()
            or individual_stays.exists()
            or bool(set(request.user.onboarding_intents or []) & individual_intents)
        )
        agency_data = AgencySerializer(agencies, many=True, context={"request": request}).data
        context = request.query_params.get("context", "").strip()

        if not context:
            if has_individual:
                context = "individual"
            elif agency_data:
                context = f"agency:{agency_data[0]['id']}"
            else:
                return Response(
                    {
                        "mode": "onboarding",
                        "contexts": {"individual": False, "agencies": []},
                        "context": None,
                        "stats": None,
                        "listings": self._empty_page(),
                    }
                )

        agency = None
        profile = None
        if context == "individual":
            if not has_individual:
                raise ValidationError({"context": "Individual listing management is not set up yet."})
            base_properties = individual_properties
            base_stays = individual_stays
            context_data = {"kind": "individual", "id": None, "name": "Individual", "role": "OWNER"}
        elif context.startswith("agency:"):
            agency_id = context.partition(":")[2]
            agency = agencies.filter(id=agency_id).first()
            if not agency:
                raise AgencyPermissionDenied()
            profile = active_profile(request.user, agency)
            base_properties = PropertyListing.objects.filter(agency=agency)
            base_stays = Stay.objects.filter(agency=agency)
            context_data = {
                "kind": "agency",
                "id": str(agency.id),
                "name": agency.name,
                "role": profile.role,
                "agency": AgencySerializer(agency, context={"request": request}).data,
            }
        else:
            raise ValidationError({"context": "Choose an available management context."})

        stats = self._stats(base_properties, base_stays)
        listings = self._listings(request, base_properties, base_stays)
        return Response(
            {
                "mode": "dashboard",
                "contexts": {"individual": has_individual, "agencies": agency_data},
                "context": context_data,
                "stats": stats,
                "listings": listings,
            }
        )

    def _agencies(self, request):
        return (
            Agency.objects.filter(agents__user=request.user, agents__is_active=True)
            .prefetch_related(
                models.Prefetch(
                    "agents",
                    queryset=AgentProfile.objects.filter(user=request.user, is_active=True),
                    to_attr="_prefetched_agents",
                )
            )
            .distinct()
            .order_by("name")
        )

    def _stats(self, properties, stays):
        published = (
            properties.filter(status=ListingStatus.PUBLISHED).count()
            + stays.filter(status=StayStatus.PUBLISHED).count()
        )
        enquiries = GuestEnquiry.objects.filter(Q(property__in=properties) | Q(stay__in=stays)).count()
        pending_viewings = ViewingRequest.objects.filter(
            property__in=properties,
            status__in=[ViewingStatus.PENDING, ViewingStatus.RESCHEDULE_REQUESTED],
        ).count()
        pending_bookings = Booking.objects.filter(stay__in=stays, status=BookingStatus.PENDING).count()
        return {
            "total_listings": properties.count() + stays.count(),
            "published_listings": published,
            "enquiries": enquiries,
            "pending_requests": pending_viewings + pending_bookings,
            "pending_viewings": pending_viewings,
            "pending_bookings": pending_bookings,
        }

    def _listings(self, request, properties, stays):
        search = request.query_params.get("search", "").strip()
        status_value = request.query_params.get("status", "").strip().upper()
        kind = request.query_params.get("type", "all").strip().lower()
        ordering = request.query_params.get("ordering", "newest").strip().lower()
        if kind not in {"all", "property", "stay"}:
            raise ValidationError({"type": "Choose all, property or stay."})
        if ordering not in {"newest", "oldest"}:
            raise ValidationError({"ordering": "Choose newest or oldest."})
        statuses = {choice for choice, _ in ListingStatus.choices} | {choice for choice, _ in StayStatus.choices}
        if status_value and status_value not in statuses:
            raise ValidationError({"status": "Choose a valid listing status."})

        if search:
            properties = properties.filter(
                Q(title__icontains=search)
                | Q(public_id__icontains=search)
                | Q(town__icontains=search)
                | Q(suburb__icontains=search)
            )
            stays = stays.filter(
                Q(name__icontains=search)
                | Q(public_id__icontains=search)
                | Q(town__icontains=search)
                | Q(suburb__icontains=search)
            )
        if status_value:
            properties = properties.filter(status=status_value)
            stays = stays.filter(status=status_value)
        if kind == "property":
            stays = stays.none()
        elif kind == "stay":
            properties = properties.none()

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(20, max(1, int(request.query_params.get("page_size", 6))))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"page": "Page values must be whole numbers."}) from exc

        total = properties.count() + stays.count()
        offset = (page - 1) * page_size
        window = offset + page_size
        order = "updated_at" if ordering == "oldest" else "-updated_at"
        property_items = list(properties.prefetch_related("images").order_by(order)[:window])
        stay_items = list(stays.prefetch_related("images", "room_types").order_by(order)[:window])
        combined = [self._property_item(request, item) for item in property_items] + [
            self._stay_item(request, item) for item in stay_items
        ]
        combined.sort(key=lambda item: item["updated_at"], reverse=ordering == "newest")
        results = combined[offset : offset + page_size]
        pages = math.ceil(total / page_size) if total else 0
        return {
            "count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": pages,
            "next_page": page + 1 if page < pages else None,
            "previous_page": page - 1 if page > 1 and pages else None,
            "results": results,
        }

    def _property_item(self, request, item):
        return {
            "id": str(item.id),
            "kind": "property",
            "public_id": item.public_id,
            "slug": item.slug,
            "title": item.title,
            "subtype": item.get_property_type_display(),
            "status": item.status,
            "town": item.town,
            "suburb": item.suburb,
            "cover_image": self._cover_url(request, item.images.all()),
            "updated_at": item.updated_at.isoformat(),
            "facts": [
                f"{item.bedrooms} bed{'s' if item.bedrooms != 1 else ''}" if item.bedrooms is not None else "",
                f"{item.bathrooms} bath{'s' if item.bathrooms != 1 else ''}" if item.bathrooms is not None else "",
            ],
            "edit_url": f"/account/manage/properties/{item.id}/edit",
            "public_url": f"/properties/{item.slug}" if item.status == ListingStatus.PUBLISHED else None,
        }

    def _stay_item(self, request, item):
        rooms = list(item.room_types.all())
        return {
            "id": str(item.id),
            "kind": "stay",
            "public_id": item.public_id,
            "slug": item.slug,
            "title": item.name,
            "subtype": item.get_stay_type_display(),
            "status": item.status,
            "town": item.town,
            "suburb": item.suburb,
            "cover_image": self._cover_url(request, item.images.all()),
            "updated_at": item.updated_at.isoformat(),
            "facts": [f"{len(rooms)} room type{'s' if len(rooms) != 1 else ''}"],
            "edit_url": f"/account/manage/stays/{item.id}/edit",
            "rooms_url": f"/account/manage/stays/{item.id}/rooms",
            "availability_url": f"/account/manage/stays/{item.id}/calendar",
            "public_url": f"/stays/{item.slug}" if item.status == StayStatus.PUBLISHED else None,
        }

    def _cover_url(self, request, images):
        items = list(images)
        image = next((item for item in items if item.is_cover), items[0] if items else None)
        if not image:
            return None
        url = image.image.url
        return request.build_absolute_uri(url) if not str(url).startswith(("http://", "https://")) else url

    def _empty_page(self):
        return {
            "count": 0,
            "page": 1,
            "page_size": 6,
            "total_pages": 0,
            "next_page": None,
            "previous_page": None,
            "results": [],
        }


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
