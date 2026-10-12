"""Stay moderation uses the same decision rules as property moderation."""
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from stays.models import Stay, StayStatus
from stays.serializers import StayDetailSerializer
from .models import ModerationAuditEvent
from .serializers import (
    StaffUserSummarySerializer, StaffListingReportSerializer,
    ModerationAuditEventSerializer, StaffModerationActionSerializer,
)
from .views import StaffPropertyModerationViewSet, PROPERTY_MODERATION_PERMS


class StaffStayPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.is_staff:
            return False
        permission = PROPERTY_MODERATION_PERMS.get(view.action, "properties.review_propertylisting")
        permission = permission.replace("properties.", "stays.").replace("propertylisting", "stay")
        return user.is_superuser or user.has_perm(permission)


class StaffStaySerializer(StayDetailSerializer):
    owner = StaffUserSummarySerializer(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    audit_events = serializers.SerializerMethodField()
    reports = serializers.SerializerMethodField()
    verification_requests = serializers.SerializerMethodField()
    verification_request_count = serializers.SerializerMethodField()
    verification_document_count = serializers.SerializerMethodField()

    class Meta(StayDetailSerializer.Meta):
        exclude = ("location",)

    def get_audit_events(self, obj):
        return ModerationAuditEventSerializer(
            obj.moderationauditevent_set.select_related("actor").order_by("-created_at")[:25], many=True
        ).data

    def get_reports(self, obj):
        return StaffListingReportSerializer(
            obj.listingreport_set.select_related("reporter").order_by("-created_at")[:10], many=True
        ).data

    def get_verification_requests(self, obj):
        user = self.context["request"].user
        if not user.has_perm("verification.review_verificationrequest"):
            return []
        from verification.models import VerificationRequest
        return list(VerificationRequest.objects.filter(stay=obj).exclude(status="DRAFT")
                    .order_by("-created_at").values("id", "status")[:10])

    def _evidence_counts(self, obj):
        if (getattr(self.context.get("view"), "action", "") == "list"
                or not self.context["request"].user.has_perm("verification.review_verificationrequest")):
            return None
        from verification.models import VerificationRequest
        cache = getattr(self, "_evidence_count_cache", {})
        if obj.pk not in cache:
            cache[obj.pk] = VerificationRequest.objects.filter(stay=obj).exclude(status="DRAFT").aggregate(
                requests=Count("id", distinct=True), documents=Count("documents", distinct=True))
            self._evidence_count_cache = cache
        return cache[obj.pk]

    def get_verification_request_count(self, obj):
        counts = self._evidence_counts(obj)
        return counts["requests"] if counts is not None else None

    def get_verification_document_count(self, obj):
        counts = self._evidence_counts(obj)
        return counts["documents"] if counts is not None else None


@method_decorator(transaction.atomic, name="dispatch")
class StaffStayModerationViewSet(StaffPropertyModerationViewSet):
    permission_classes = [StaffStayPermission]

    def get_serializer_class(self):
        return StaffStaySerializer

    def get_queryset(self):
        qs = Stay.objects.select_related("owner", "agency", "agent").prefetch_related(
            "images", "amenities", "room_types__images"
        )
        status_filter = self.request.query_params.get("status", "")
        if status_filter:
            statuses = [value.strip().upper() for value in status_filter.split(",")]
            if any(value not in StayStatus.values for value in statuses):
                raise ValidationError({"status": "Choose valid stay statuses."})
            qs = qs.filter(status__in=statuses)
        elif self.action == "list":
            qs = qs.exclude(status__in=[StayStatus.DRAFT, StayStatus.PAUSED])
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(public_id__icontains=search)
                           | Q(town__icontains=search) | Q(owner__email__icontains=search))
        town = self.request.query_params.get("town", "").strip()
        if town:
            qs = qs.filter(town=town)
        host = self.request.query_params.get("host", "").strip()
        if host:
            try:
                host = serializers.UUIDField().run_validation(host)
            except serializers.ValidationError as error:
                raise ValidationError({"host": "Choose a valid host."}) from error
            qs = qs.filter(owner_id=host)
        ordering = self.request.query_params.get("ordering", "-submitted_at")
        if ordering not in {"-submitted_at", "submitted_at", "-created_at", "created_at", "name", "-name", "-updated_at"}:
            raise ValidationError({"ordering": "Choose an available stay ordering."})
        return qs.order_by(ordering, "-updated_at", "id")

    def get_object(self):
        stay = super().get_object()
        if self.request.method == "POST":
            from stays.entitlements import lock_owner
            with lock_owner(stay.owner_id, stay.agency_id):
                pass  # The dispatch transaction retains this lock through the action.
            locked = Stay.objects.select_for_update(of=("self",)).get(pk=stay.pk)
            if (stay.owner_id, stay.agency_id) != (locked.owner_id, locked.agency_id):
                raise ValidationError("Stay ownership changed. Reload and try again.")
            return locked
        return stay

    @action(detail=False, methods=["get"])
    def summary(self, request):
        counts = Stay.objects.aggregate(
            total=Count("id"),
            submitted=Count("id", filter=Q(status=StayStatus.SUBMITTED)),
            under_review=Count("id", filter=Q(status=StayStatus.UNDER_REVIEW)),
            approved=Count("id", filter=Q(status=StayStatus.PUBLISHED)),
            awaiting_review=Count("id", filter=Q(status__in=[StayStatus.SUBMITTED, StayStatus.UNDER_REVIEW])),
            changes_requested=Count("id", filter=Q(status=StayStatus.CHANGES_REQUESTED)),
            approved_today=Count("id", filter=Q(status=StayStatus.PUBLISHED, published_at__date=timezone.localdate())),
            rejected=Count("id", filter=Q(status=StayStatus.REJECTED)),
            suspended=Count("id", filter=Q(status=StayStatus.SUSPENDED)),
        )
        counts["towns"] = list(Stay.objects.exclude(town="").order_by("town").values_list("town", flat=True).distinct())
        hosts = Stay.objects.order_by("owner__first_name", "owner_id").values("owner_id", "owner__first_name", "owner__last_name").distinct()
        counts["hosts"] = [{"id": str(host["owner_id"]),
                            "name": f'{host["owner__first_name"]} {host["owner__last_name"]}'.strip() or "Stay host"}
                           for host in hosts]
        return Response(counts)

    def _validate_publication(self, stay):
        from stays.entitlements import check_submission
        check_submission(stay)
        rooms = list(stay.room_types.filter(is_active=True))
        if not rooms:
            raise ValidationError({"room_types": "At least one active room type is required."})
        stay.status = StayStatus.PUBLISHED
        try:
            stay.full_clean()
            for room in rooms:
                room.full_clean()
        except ModelValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages) from error

    @action(detail=True, methods=["post"])
    def approve(self, request, id=None):
        stay = self.get_object()
        if stay.status not in [StayStatus.SUBMITTED, StayStatus.UNDER_REVIEW]:
            raise ValidationError({"status": "Only submitted or under-review stays can be approved."})
        self._validate_publication(stay)
        return self._moderate(stay, StayStatus.PUBLISHED, "STAY_APPROVED", notify=True)

    @action(detail=True, methods=["post"])
    def restore(self, request, id=None):
        stay = self.get_object()
        if stay.status != StayStatus.SUSPENDED:
            raise ValidationError({"status": "Only suspended stays can be restored."})
        self._validate_publication(stay)
        return self._moderate(stay, StayStatus.PUBLISHED, "STAY_RESTORED", notify=True)

    @action(detail=True, methods=["post"], url_path="notes")
    def add_note(self, request, id=None):
        stay = self.get_object()
        serializer = StaffModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not (data.get("note") or data.get("reason")):
            raise ValidationError({"note": "An internal note is required."})
        return self._moderate(stay, stay.status, "STAY_NOTE_ADDED", data)

    def _moderate(self, listing, status, action_name, data=None, notify=False):
        action_name = action_name.replace("PROPERTY_", "STAY_")
        reason = (data or {}).get("reason") or (data or {}).get("note") or ""
        listing.status = status
        fields = ["status", "updated_at"]
        if status == StayStatus.PUBLISHED and action_name != "STAY_NOTE_ADDED":
            listing.published_at = timezone.now()
            fields.append("published_at")
        listing.save(update_fields=fields)
        from django.core.cache import cache
        cache.delete("stays:featured:v2")
        ModerationAuditEvent.objects.create(actor=self.request.user, stay=listing,
            action=action_name, reason=reason, metadata={"status": status})
        if notify:
            from notifications.models import NotificationType
            from notifications.services import notify_transactional
            label = {"STAY_APPROVED": "approved", "STAY_RESTORED": "restored",
                     "STAY_REJECTED": "rejected", "STAY_SUSPENDED": "suspended",
                     "STAY_CHANGES_REQUESTED": "sent back for changes"}[action_name]
            route = f"/stays/{listing.slug}" if status == StayStatus.PUBLISHED else f"/account/manage/stays/{listing.id}/edit"
            notify_transactional(listing.owner, NotificationType.LISTING_STATUS_UPDATE,
                f"Stay {label}", f"Your stay '{listing.name}' was {label}. {reason}".strip(),
                {"route": route, "stay_id": str(listing.id), "status": status, "action": action_name},
                f"stay-moderation:{action_name}:{listing.id}:{listing.updated_at.isoformat()}", "email_enabled")
        return Response(self.get_serializer(listing).data)
