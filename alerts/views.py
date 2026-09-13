from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from accounts.permissions import IsEmailVerified
from properties.serializers import PropertyListSerializer
from stays.serializers import StayListSerializer
from favourites.models import Favourite
from .models import SavedSearch, SearchAlertEvent, SearchType
from .serializers import SavedSearchSerializer
from .services import evaluate, matches


class SavedSearchViewSet(viewsets.ModelViewSet):
    serializer_class = SavedSearchSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]

    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)

    @action(detail=True, methods=["get"])
    def results(self, request, pk=None):
        saved = self.get_object()
        qs = matches(saved)
        page = self.paginate_queryset(qs)
        serializer = PropertyListSerializer if saved.search_type == SearchType.PROPERTY else StayListSerializer
        data = serializer(page, many=True, context={"request": request}).data
        return self.get_paginated_response(data)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        saved = self.get_object()
        items = evaluate(saved)
        serializer = PropertyListSerializer if saved.search_type == SearchType.PROPERTY else StayListSerializer
        return Response(
            {
                "saved_search_id": str(saved.id),
                "new_matches": len(items),
                "matches": serializer(items, many=True, context={"request": request}).data,
            }
        )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def seeker_summary(request):
    from agencies.models import AgentProfile
    from bookings.models import Booking, BookingStatus, ViewingRequest, ViewingStatus
    from django.db.models import Exists, OuterRef, Q
    from django.utils import timezone
    from messaging.models import ConversationParticipant, Message
    from properties.models import ListingStatus, PropertyListing
    from stays.models import Stay, StayStatus
    from verification.models import RequestStatus, VerificationRequest

    today = timezone.localdate()
    fav = Favourite.objects.filter(user=request.user)
    searches = SavedSearch.objects.filter(user=request.user, notifications_enabled=True).exclude(frequency="OFF")
    events = SearchAlertEvent.objects.filter(saved_search__user=request.user, notified_at__isnull=True).count()
    bookings = Booking.objects.filter(guest=request.user)
    next_viewing = (
        ViewingRequest.objects.filter(
            requester=request.user,
            requested_date__gte=today,
            status__in=[ViewingStatus.PENDING, ViewingStatus.CONFIRMED, ViewingStatus.RESCHEDULE_REQUESTED],
        )
        .select_related("property")
        .order_by("requested_date", "requested_time")
        .first()
    )
    next_stay = (
        bookings.filter(status=BookingStatus.CONFIRMED, check_in__gte=today)
        .select_related("stay")
        .order_by("check_in")
        .first()
    )

    active_participant = ConversationParticipant.objects.filter(
        conversation_id=OuterRef("conversation_id"), user=request.user, is_active=True
    ).filter(Q(last_read_at__isnull=True) | Q(last_read_at__lt=OuterRef("created_at")))
    unread_messages = (
        Message.objects.exclude(sender=request.user)
        .annotate(is_unread=Exists(active_participant))
        .filter(is_unread=True)
        .count()
    )

    membership = AgentProfile.objects.filter(user=request.user, is_active=True).select_related("agency").first()
    agency = membership.agency if membership else None
    managed_properties = PropertyListing.objects.filter(
        Q(owner=request.user)
        | Q(agent__user=request.user, agent__is_active=True)
        | Q(agency__agents__user=request.user, agency__agents__is_active=True)
    ).distinct()
    managed_stays = Stay.objects.filter(
        Q(owner=request.user)
        | Q(agent__user=request.user, agent__is_active=True)
        | Q(agency__agents__user=request.user, agency__agents__is_active=True)
    ).distinct()
    advertiser_summary = None
    if managed_properties.exists() or managed_stays.exists() or agency:
        advertiser_summary = {
            "published_property_count": managed_properties.filter(status=ListingStatus.PUBLISHED).count(),
            "pending_property_count": managed_properties.filter(
                status__in=[ListingStatus.SUBMITTED, ListingStatus.UNDER_REVIEW]
            ).count(),
            "published_stay_count": managed_stays.filter(status=StayStatus.PUBLISHED).count(),
            "pending_stay_count": managed_stays.filter(
                status__in=[StayStatus.SUBMITTED, StayStatus.UNDER_REVIEW]
            ).count(),
            "has_properties": managed_properties.exists(),
            "has_stays": managed_stays.exists(),
            "agency": {"id": str(agency.id), "name": agency.name} if agency else None,
        }

    verification_attention = list(
        VerificationRequest.objects.filter(
            applicant=request.user,
            status__in=[
                RequestStatus.CHANGES_REQUESTED,
                RequestStatus.DRAFT,
                RequestStatus.SUBMITTED,
                RequestStatus.UNDER_REVIEW,
            ],
        )
        .values("id", "verification_type", "status", "reviewer_notes", "updated_at")
        .order_by("-updated_at")[:6]
    )
    verification_priority = {
        RequestStatus.CHANGES_REQUESTED: 0,
        RequestStatus.DRAFT: 1,
        RequestStatus.SUBMITTED: 2,
        RequestStatus.UNDER_REVIEW: 2,
    }
    verification_attention.sort(key=lambda item: verification_priority.get(item["status"], 9))

    return Response(
        {
            "total_saved_properties": fav.filter(property__isnull=False).count(),
            "total_saved_stays": fav.filter(stay__isnull=False).count(),
            "active_saved_searches": searches.count(),
            "new_alert_count": events,
            "unread_notifications": request.user.notifications.filter(is_read=False).count(),
            "upcoming_stays": bookings.filter(
                status=BookingStatus.CONFIRMED, check_in__gte=timezone.localdate()
            ).count(),
            "pending_bookings": bookings.filter(status=BookingStatus.PENDING).count(),
            "confirmed_bookings": bookings.filter(status=BookingStatus.CONFIRMED).count(),
            "unread_messages": unread_messages,
            "next_viewing": (
                {
                    "id": str(next_viewing.id),
                    "property_title": next_viewing.property.title,
                    "property_slug": next_viewing.property.slug,
                    "requested_date": next_viewing.requested_date,
                    "requested_time": next_viewing.requested_time,
                    "status": next_viewing.status,
                }
                if next_viewing
                else None
            ),
            "next_stay": (
                {
                    "id": str(next_stay.id),
                    "stay_name": next_stay.stay.name,
                    "stay_slug": next_stay.stay.slug,
                    "check_in": next_stay.check_in,
                    "check_out": next_stay.check_out,
                    "status": next_stay.status,
                }
                if next_stay
                else None
            ),
            "verification_attention": verification_attention,
            "advertiser_summary": advertiser_summary,
        }
    )
