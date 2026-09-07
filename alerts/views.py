from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from properties.serializers import PropertyListSerializer
from stays.serializers import StayListSerializer
from favourites.models import Favourite
from .models import SavedSearch, SearchAlertEvent, SearchType
from .serializers import SavedSearchSerializer
from .services import evaluate, matches


class SavedSearchViewSet(viewsets.ModelViewSet):
    serializer_class = SavedSearchSerializer
    permission_classes = [permissions.IsAuthenticated]

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
    from bookings.models import Booking, BookingStatus
    from django.utils import timezone

    fav = Favourite.objects.filter(user=request.user)
    searches = SavedSearch.objects.filter(user=request.user, notifications_enabled=True).exclude(frequency="OFF")
    events = SearchAlertEvent.objects.filter(saved_search__user=request.user, notified_at__isnull=True).count()
    bookings = Booking.objects.filter(guest=request.user)
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
        }
    )
