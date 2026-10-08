from django.utils import timezone
from django.db import models
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from accounts.permissions import IsEmailVerified
from properties.models import PropertyListing, ListingStatus
from properties.permissions import can_manage_property
from messaging.services import create_conversation, system_message
from .models import *
from .serializers import BookingCreateSerializer, BookingSerializer, ViewingSerializer
from .services import PriceChanged, create_booking, transition


class ViewingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ViewingSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]

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
@permission_classes([permissions.IsAuthenticated, IsEmailVerified])
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
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]
    lookup_field = "id"

    def get_queryset(self):
        u = self.request.user
        manager = (
            models.Q(stay__owner=u)
            | models.Q(stay__agent__user=u, stay__agent__is_active=True)
            | models.Q(stay__agency__agents__user=u, stay__agency__agents__is_active=True)
        )
        if u.is_staff:
            manager = models.Q()
        qs = (
            Booking.objects.filter(manager if u.is_staff else models.Q(guest=u) | manager)
            .select_related("stay", "room_type", "guest")
            .distinct()
        )
        p = self.request.query_params
        for f in ("stay", "room_type", "status", "payment_status"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("scope") == "manager":
            qs = qs.filter(manager)
        if p.get("scope") == "guest":
            qs = qs.filter(guest=u)
        if p.get("idempotency_key"):
            qs = qs.filter(guest=u, idempotency_key=p["idempotency_key"])
        return qs.order_by("-created_at", "-id")

    def _go(self, target):
        try:
            obj = transition(self.get_object(), target, self.request.user,
                             reason=serializers.CharField(max_length=1000, allow_blank=True).run_validation(self.request.data.get("reason", "")),
                             note=serializers.CharField(max_length=1000, allow_blank=True).run_validation(self.request.data.get("note", "")))
        except DjangoValidationError as e:
            raise ValidationError(e.message_dict if hasattr(e, "message_dict") else e.messages) from e
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
@permission_classes([permissions.IsAuthenticated, IsEmailVerified])
def create_stay_booking(request, stay_id):
    from stays.models import Stay, RoomType

    s = BookingCreateSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    data = dict(s.validated_data)
    if data["guest_email"].casefold() != request.user.email.casefold():
        raise ValidationError({"guest_email": "Use your account email for this booking."})
    stay = get_object_or_404(Stay, pk=stay_id)
    room = get_object_or_404(RoomType, pk=data.pop("room_type"), stay=stay)
    key = request.headers.get("Idempotency-Key")
    if key is not None:
        key = serializers.CharField(max_length=100).run_validation(key)
    try:
        obj = create_booking(
            guest=request.user,
            stay=stay,
            room_type=room,
            **data,
            idempotency_key=key,
        )
    except PriceChanged as e:
        return Response({"code": "price_changed", "message": str(e.messages[0]), "new_total": e.total, "nightly_prices": e.nightly_prices}, status=409)
    except DjangoValidationError as e:
        raise ValidationError(e.message_dict if hasattr(e, "message_dict") else e.messages) from e
    return Response(BookingSerializer(obj).data, status=201)
