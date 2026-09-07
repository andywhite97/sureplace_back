from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError as APIValidationError
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from .models import *
from .serializers import *
from .services import can_access, notify_message


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        qs = (
            Conversation.objects.filter(
                Q(participants__user=u)
                | Q(property__owner=u)
                | Q(stay__owner=u)
                | Q(property__agency__agents__user=u)
                | Q(stay__agency__agents__user=u)
            )
            .distinct()
            .select_related("property", "stay")
            .prefetch_related("participants__user", "messages")
        )
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        c = self.get_object()
        if not can_access(request.user, c):
            raise PermissionDenied()
        if request.method == "GET":
            page = self.paginate_queryset(c.messages.order_by("-created_at"))
            return self.get_paginated_response(MessageSerializer(page, many=True, context={"request": request}).data)
        kind = request.data.get("message_type", "TEXT")
        if kind not in ("TEXT", "ENQUIRY", "BOOKING_ENQUIRY"):
            raise APIValidationError("This message type is server controlled.")
        m = Message.objects.create(
            conversation=c, sender=request.user, message_type=kind, body=request.data.get("body", "")
        )
        c.last_message_at = m.created_at
        c.save()
        notify_message(m)
        return Response(MessageSerializer(m, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        c = self.get_object()
        p = c.participants.get(user=request.user)
        p.last_read_at = timezone.now()
        p.save()
        return Response({"unread_count": 0})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AnonRateThrottle])
def guest_enquiry(request):
    s = GuestSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    enquiry = s.save()
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    target = enquiry.property or enquiry.stay
    manager = target.agent.user if target.agent_id else target.owner
    notify_transactional(
        manager,
        NotificationType.GUEST_ENQUIRY,
        "New guest enquiry",
        f"{enquiry.name} sent an enquiry.",
        {"route": "/manager/enquiries"},
        f"guest-enquiry:{enquiry.id}",
        "new_message_email",
    )
    return Response(GuestSerializer(enquiry).data, status=201)


class MessageViewSet(viewsets.GenericViewSet):
    queryset = Message.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["delete"])
    def remove(self, request, pk=None):
        m = self.get_object()
        if m.sender_id != request.user.id:
            raise PermissionDenied()
        m.deleted_at = timezone.now()
        m.save()
        return Response(status=204)
