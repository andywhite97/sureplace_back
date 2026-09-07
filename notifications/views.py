from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Notification, NotificationPreference
from .serializers import NotificationSerializer, PreferenceSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        p = self.request.query_params
        if p.get("unread") is not None:
            qs = qs.filter(is_read=p["unread"].lower() == "true")
        if p.get("notification_type"):
            qs = qs.filter(notification_type=p["notification_type"])
        return qs

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, r, pk=None):
        n = self.get_object()
        n.is_read = True
        n.read_at = timezone.now()
        n.save(update_fields=["is_read", "read_at"])
        return Response(self.get_serializer(n).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all(self, r):
        count = self.get_queryset().filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({"updated": count})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, r):
        return Response({"unread_count": self.get_queryset().filter(is_read=False).count()})


class PreferenceViewSet(viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = PreferenceSerializer

    @action(detail=False, methods=["get", "patch"])
    def me(self, r):
        obj, _ = NotificationPreference.objects.get_or_create(user=r.user)
        s = self.get_serializer(obj, data=r.data, partial=True) if r.method == "PATCH" else self.get_serializer(obj)
        if r.method == "PATCH":
            s.is_valid(raise_exception=True)
            s.save()
        return Response(s.data)
