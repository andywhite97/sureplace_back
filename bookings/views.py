from datetime import date
from django.utils import timezone
from django.db import models
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from properties.models import PropertyListing, ListingStatus
from properties.permissions import can_manage_property
from messaging.services import create_conversation, system_message
from .models import *
from .serializers import BookingSerializer, ViewingSerializer
from .services import create_booking, transition


class ViewingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ViewingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ViewingRequest.objects.filter(
            models.Q(requester=self.request.user)
            | models.Q(property__owner=self.request.user)
            | models.Q(property__agency__agents__user=self.request.user)
        ).distinct()
        if self.request.query_params.get("scope") == "manager":
            qs = qs.filter(
                models.Q(property__owner=self.request.user)
                | models.Q(property__agency__agents__user=self.request.user)
            )
        return qs

    def _change(self, status_value, text, manager=False):
        obj = self.get_object()
        if manager and not can_manage_property(self.request.user, obj.property):
            raise PermissionDenied()
        if not manager and obj.requester_id != self.request.user.id:
            raise PermissionDenied()
        obj.status = status_value
        if status_value == ViewingStatus.CONFIRMED:
            obj.confirmed_at = timezone.now()
        if status_value == ViewingStatus.CANCELLED:
            obj.cancelled_at = timezone.now()
        if status_value == ViewingStatus.COMPLETED:
            obj.completed_at = timezone.now()
        obj.save()
        system_message(obj.conversation, text)
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        kinds = {
            ViewingStatus.CONFIRMED: NotificationType.VIEWING_CONFIRMED,
            ViewingStatus.CANCELLED: NotificationType.VIEWING_CANCELLED,
            ViewingStatus.RESCHEDULE_REQUESTED: NotificationType.VIEWING_RESCHEDULED,
        }
        recipient = obj.requester if manager else obj.property.owner
        notify_transactional(
            recipient,
            kinds.get(status_value, NotificationType.SYSTEM),
            text,
            text,
            {"route": f"/account/viewings/{obj.id}", "viewing_id": str(obj.id)},
            f"viewing:{status_value}:{obj.id}",
            "viewing_updates_email",
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def confirm(self, r, pk=None):
        return self._change(ViewingStatus.CONFIRMED, "Viewing confirmed", True)

    @action(detail=True, methods=["post"])
    def decline(self, r, pk=None):
        return self._change(ViewingStatus.DECLINED, "Viewing declined", True)

    @action(detail=True, methods=["post"])
    def cancel(self, r, pk=None):
        return self._change(ViewingStatus.CANCELLED, "Viewing cancelled")

    @action(detail=True, methods=["post"])
    def complete(self, r, pk=None):
        return self._change(ViewingStatus.COMPLETED, "Viewing completed", True)

    @action(detail=True, methods=["post"])
    def reschedule(self, r, pk=None):
        return self._change(ViewingStatus.RESCHEDULE_REQUESTED, "Viewing reschedule requested")


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def create_viewing(request, property_id):
    prop = PropertyListing.objects.get(id=property_id)
    if prop.status != ListingStatus.PUBLISHED or prop.owner_id == request.user.id:
        raise ValidationError("Property unavailable or owned by requester.")
    s = ViewingSerializer(data={**request.data, "property": str(prop.id)})
    s.is_valid(raise_exception=True)
    if ViewingRequest.objects.filter(
        property=prop,
        requester=request.user,
        requested_date=s.validated_data["requested_date"],
        requested_time=s.validated_data["requested_time"],
        status__in=[ViewingStatus.PENDING, ViewingStatus.CONFIRMED, ViewingStatus.RESCHEDULE_REQUESTED],
    ).exists():
        raise ValidationError("An active request already exists for this time.")
    c = create_conversation(request.user, "Viewing requested", property=prop)
    obj = s.save(requester=request.user, agent=prop.agent, conversation=c)
    system_message(c, f"Viewing requested for {obj.requested_date} at {obj.requested_time}", "VIEWING_REQUEST")
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    manager = prop.agent.user if prop.agent_id else prop.owner
    notify_transactional(
        manager,
        NotificationType.VIEWING_REQUEST,
        "New viewing request",
        f"Viewing requested for {obj.requested_date} at {obj.requested_time}.",
        {"route": f"/viewings/{obj.id}", "viewing_id": str(obj.id)},
        f"viewing-request:{obj.id}",
        "viewing_updates_email",
    )
    return Response(ViewingSerializer(obj).data, status=201)


class BookingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        u = self.request.user
        qs = (
            Booking.objects.filter(
                models.Q(guest=u)
                | models.Q(stay__owner=u)
                | models.Q(stay__agent__user=u)
                | models.Q(stay__agency__agents__user=u)
            )
            .select_related("stay", "room_type", "guest")
            .distinct()
        )
        p = self.request.query_params
        for f in ("stay", "room_type", "status", "payment_status"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("scope") == "manager":
            qs = qs.filter(
                models.Q(stay__owner=u)
                | models.Q(stay__agent__user=u)
                | models.Q(stay__agency__agents__user=u)
            )
        return qs.order_by("-created_at")

    def _go(self, target):
        try:
            obj = transition(self.get_object(), target, self.request.user)
        except Exception as e:
            raise ValidationError(getattr(e, "messages", str(e)))
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"])
    def confirm(self, r, id=None):
        return self._go(BookingStatus.CONFIRMED)

    @action(detail=True, methods=["post"])
    def decline(self, r, id=None):
        return self._go(BookingStatus.DECLINED)

    @action(detail=True, methods=["post"])
    def cancel(self, r, id=None):
        return self._go(BookingStatus.CANCELLED)

    @action(detail=True, methods=["post"])
    def complete(self, r, id=None):
        return self._go(BookingStatus.COMPLETED)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def create_stay_booking(request, stay_id):
    from stays.models import Stay, RoomType

    stay = Stay.objects.get(pk=stay_id)
    room = RoomType.objects.get(pk=request.data.get("room_type"))
    try:
        obj = create_booking(
            guest=request.user,
            stay=stay,
            room_type=room,
            check_in=date.fromisoformat(request.data["check_in"]),
            check_out=date.fromisoformat(request.data["check_out"]),
            adults=int(request.data.get("adults", 1)),
            children=int(request.data.get("children", 0)),
            rooms=int(request.data.get("rooms", 1)),
            guest_name=request.data["guest_name"],
            guest_email=request.data["guest_email"],
            guest_phone=request.data.get("guest_phone", ""),
            special_requests=request.data.get("special_requests", ""),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    except Exception as e:
        raise ValidationError(getattr(e, "messages", str(e)))
    return Response(BookingSerializer(obj).data, status=201)
