from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from properties.models import ListingStatus, PropertyListing
from .models import ListingReport, ModerationAuditEvent
from .serializers import (
    ModerationAuditEventSerializer,
    ReportSerializer,
    STAFF_REVIEW_STATUSES,
    StaffModerationActionSerializer,
    StaffPropertyDetailSerializer,
    StaffPropertySerializer,
    StaffDashboardListingSerializer,
    StaffDashboardActivitySerializer,
)

PROPERTY_MODERATION_PERMS = {
    "list": "properties.review_propertylisting",
    "retrieve": "properties.review_propertylisting",
    "summary": "properties.review_propertylisting",
    "audit": "properties.review_propertylisting",
    "reports": "properties.review_propertylisting",
    "start_review": "properties.review_propertylisting",
    "approve": "properties.approve_propertylisting",
    "request_changes": "properties.request_changes_propertylisting",
    "reject": "properties.reject_propertylisting",
    "suspend": "properties.suspend_propertylisting",
    "restore": "properties.restore_propertylisting",
    "add_note": "properties.add_note_propertylisting",
}


class StaffPropertyModerationPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_staff:
            return False
        if user.is_superuser:
            return True
        required = PROPERTY_MODERATION_PERMS.get(getattr(view, "action", ""), "properties.review_propertylisting")
        return user.has_perm(required)


class ReportCreateViewSet(viewsets.ModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["post", "head", "options"]

    def get_queryset(self):
        return ListingReport.objects.none()

    def perform_create(self, s):
        s.save(reporter=self.request.user)


class ReportReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ListingReport.objects.select_related("reporter", "property", "stay", "assigned_to")
    serializer_class = ReportSerializer
    permission_classes = [permissions.DjangoModelPermissions]

    def _set(self, status):
        report = self.get_object()
        report.status = status
        report.assigned_to = report.assigned_to or self.request.user
        report.reviewed_at = timezone.now()
        report.resolution_notes = self.request.data.get("notes", "")
        report.save()
        ModerationAuditEvent.objects.create(
            actor=self.request.user,
            action=f"REPORT_{status}",
            property=report.property,
            stay=report.stay,
            report=report,
            reason=report.resolution_notes,
        )
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        notify_transactional(
            report.reporter,
            NotificationType.SYSTEM,
            f"Report {status.lower().replace('_',' ')}",
            f"Your listing report was {status.lower().replace('_',' ')}.",
            {"route": "/account/reports"},
            f"report:{status}:{report.id}",
            "email_enabled",
        )
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def assign(self, r, pk=None):
        report = self.get_object()
        report.assigned_to = r.user
        report.status = "UNDER_REVIEW"
        report.save()
        ModerationAuditEvent.objects.create(
            actor=r.user, action="REPORT_ASSIGNED", property=report.property, stay=report.stay, report=report
        )
        return Response(self.get_serializer(report).data)

    @action(detail=True, methods=["post"])
    def resolve(self, r, pk=None):
        return self._set("RESOLVED")

    @action(detail=True, methods=["post"])
    def dismiss(self, r, pk=None):
        return self._set("DISMISSED")


class StaffPropertyModerationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StaffPropertySerializer
    permission_classes = [StaffPropertyModerationPermission]
    lookup_field = "id"

    def get_queryset(self):
        queryset = (
            PropertyListing.objects.select_related("owner", "agency")
            .prefetch_related("images")
            .annotate(
                open_reports_count=Count(
                    "listingreport",
                    filter=Q(listingreport__status__in=["OPEN", "UNDER_REVIEW"]),
                    distinct=True,
                )
            )
        )
        status_filter = self.request.query_params.get("status", "").strip()
        if status_filter:
            statuses = [item.strip().upper() for item in status_filter.split(",") if item.strip()]
            invalid = [item for item in statuses if item not in ListingStatus.values]
            if invalid:
                raise ValidationError({"status": f"Invalid status: {', '.join(invalid)}"})
            queryset = queryset.filter(status__in=statuses)
        elif self.action == "list":
            queryset = queryset.filter(status__in=STAFF_REVIEW_STATUSES)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(public_id__icontains=search)
                | Q(owner__email__icontains=search)
                | Q(town__icontains=search)
                | Q(region__icontains=search)
                | Q(agency__name__icontains=search)
            )
        ordering = self.request.query_params.get("ordering", "-created_at")
        allowed = {"created_at", "-created_at", "updated_at", "-updated_at", "price", "-price", "status"}
        if ordering not in allowed:
            raise ValidationError({"ordering": f"Choose one of: {', '.join(sorted(allowed))}."})
        return queryset.order_by(ordering, "-created_at").distinct()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StaffPropertyDetailSerializer
        return StaffPropertySerializer

    @action(detail=False, methods=["get"])
    def summary(self, request):
        from verification.models import VerificationRequest, RequestStatus, VerificationType

        today = timezone.localdate()
        pending = [ListingStatus.SUBMITTED, ListingStatus.UNDER_REVIEW]
        counts = PropertyListing.objects.aggregate(
            awaiting_review=Count("id", filter=Q(status__in=pending)),
            approved_today=Count("id", filter=Q(status=ListingStatus.PUBLISHED, published_at__date=today)),
            changes_requested=Count("id", filter=Q(status=ListingStatus.CHANGES_REQUESTED)),
            rejected=Count("id", filter=Q(status=ListingStatus.REJECTED)),
            suspended=Count("id", filter=Q(status=ListingStatus.SUSPENDED)),
        )
        counts["open_reports"] = ListingReport.objects.filter(property__isnull=False, status="OPEN").count()
        counts["agency_reviews"] = None
        counts["verification_requests"] = None
        if request.user.has_perm("verification.review_verificationrequest"):
            verification = VerificationRequest.objects.filter(
                status__in=[RequestStatus.SUBMITTED, RequestStatus.UNDER_REVIEW]
            ).aggregate(
                agency_reviews=Count("id", filter=Q(verification_type=VerificationType.AGENCY)),
                verification_requests=Count("id"),
            )
            counts.update(verification)
        latest = (
            PropertyListing.objects.filter(status__in=pending)
            .select_related("owner", "agency")
            .prefetch_related("images")
            .annotate(
                open_reports_count=Count(
                    "listingreport", filter=Q(listingreport__status__in=["OPEN", "UNDER_REVIEW"]), distinct=True
                )
            )
            .order_by("-updated_at", "-created_at", "id")[:5]
        )
        activity = (
            ModerationAuditEvent.objects.filter(property__isnull=False)
            .select_related("actor", "property")
            .order_by("-created_at", "id")[:7]
        )
        return Response(
            {
                **counts,
                "latest_listings": StaffDashboardListingSerializer(
                    latest, many=True, context=self.get_serializer_context()
                ).data,
                "recent_activity": StaffDashboardActivitySerializer(activity, many=True).data,
            }
        )

    @action(detail=True, methods=["get"])
    def audit(self, request, id=None):
        listing = self.get_object()
        events = listing.moderationauditevent_set.select_related("actor").order_by("-created_at")
        page = self.paginate_queryset(events)
        if page is not None:
            return self.get_paginated_response(ModerationAuditEventSerializer(page, many=True).data)
        return Response(ModerationAuditEventSerializer(events, many=True).data)

    @action(detail=True, methods=["post"], url_path="start-review")
    def start_review(self, request, id=None):
        listing = self.get_object()
        if listing.status != ListingStatus.SUBMITTED:
            raise ValidationError({"status": "Only submitted listings can be moved under review."})
        return self._moderate(listing, ListingStatus.UNDER_REVIEW, "PROPERTY_REVIEW_STARTED")

    @action(detail=True, methods=["post"])
    def approve(self, request, id=None):
        listing = self.get_object()
        if listing.status not in {ListingStatus.SUBMITTED, ListingStatus.UNDER_REVIEW}:
            raise ValidationError({"status": "Only submitted or under-review listings can be approved."})
        listing.status = ListingStatus.PUBLISHED
        try:
            listing.full_clean()
        except Exception as exc:
            if hasattr(exc, "message_dict"):
                raise ValidationError(exc.message_dict) from exc
            raise
        return self._moderate(listing, ListingStatus.PUBLISHED, "PROPERTY_APPROVED", notify=True)

    @action(detail=True, methods=["post"], url_path="request-changes")
    def request_changes(self, request, id=None):
        listing = self.get_object()
        serializer = StaffModerationActionSerializer(data=request.data, context={"action": "request_changes"})
        serializer.is_valid(raise_exception=True)
        if listing.status not in {ListingStatus.SUBMITTED, ListingStatus.UNDER_REVIEW}:
            raise ValidationError({"status": "Only submitted or under-review listings can receive change requests."})
        return self._moderate(
            listing,
            ListingStatus.CHANGES_REQUESTED,
            "PROPERTY_CHANGES_REQUESTED",
            serializer.validated_data,
            notify=True,
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, id=None):
        listing = self.get_object()
        serializer = StaffModerationActionSerializer(data=request.data, context={"action": "reject"})
        serializer.is_valid(raise_exception=True)
        if listing.status not in {ListingStatus.SUBMITTED, ListingStatus.UNDER_REVIEW, ListingStatus.CHANGES_REQUESTED}:
            raise ValidationError({"status": "Only review-stage listings can be rejected."})
        return self._moderate(
            listing, ListingStatus.REJECTED, "PROPERTY_REJECTED", serializer.validated_data, notify=True
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, id=None):
        listing = self.get_object()
        serializer = StaffModerationActionSerializer(data=request.data, context={"action": "suspend"})
        serializer.is_valid(raise_exception=True)
        if listing.status != ListingStatus.PUBLISHED:
            raise ValidationError({"status": "Only published listings can be suspended."})
        return self._moderate(
            listing, ListingStatus.SUSPENDED, "PROPERTY_SUSPENDED", serializer.validated_data, notify=True
        )

    @action(detail=True, methods=["post"])
    def restore(self, request, id=None):
        listing = self.get_object()
        if listing.status != ListingStatus.SUSPENDED:
            raise ValidationError({"status": "Only suspended listings can be restored."})
        return self._moderate(listing, ListingStatus.PUBLISHED, "PROPERTY_RESTORED", notify=True)

    @action(detail=True, methods=["post"], url_path="notes")
    def add_note(self, request, id=None):
        listing = self.get_object()
        serializer = StaffModerationActionSerializer(data=request.data, context={"action": "add_note"})
        serializer.is_valid(raise_exception=True)
        note = serializer.validated_data.get("note") or serializer.validated_data.get("reason") or ""
        if not note.strip():
            raise ValidationError({"note": "A note is required."})
        ModerationAuditEvent.objects.create(
            actor=request.user,
            action="PROPERTY_NOTE_ADDED",
            property=listing,
            reason=note,
        )
        return Response(StaffPropertyDetailSerializer(listing, context=self.get_serializer_context()).data)

    def _moderate(self, listing, status, action_name, data=None, notify=False):
        data = data or {}
        reason = data.get("reason") or data.get("note") or ""
        listing.status = status
        update_fields = ["status", "updated_at"]
        if status == ListingStatus.PUBLISHED:
            listing.published_at = timezone.now()
            update_fields.append("published_at")
        listing.save(update_fields=update_fields)
        ModerationAuditEvent.objects.create(
            actor=self.request.user,
            action=action_name,
            property=listing,
            reason=reason,
            metadata={"status": status},
        )
        if notify:
            self._notify_owner(listing, action_name, reason)
        return Response(StaffPropertyDetailSerializer(listing, context=self.get_serializer_context()).data)

    def _notify_owner(self, listing, action_name, reason):
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        labels = {
            "PROPERTY_APPROVED": "approved",
            "PROPERTY_CHANGES_REQUESTED": "needs changes",
            "PROPERTY_REJECTED": "rejected",
            "PROPERTY_SUSPENDED": "suspended",
            "PROPERTY_RESTORED": "restored",
        }
        public_actions = {"PROPERTY_APPROVED", "PROPERTY_RESTORED"}
        label = labels.get(action_name, "updated")
        message = f"Your listing '{listing.title}' was {label} by SurePlace moderation."
        if reason:
            message = f"{message} Feedback: {reason}"
        route = (
            f"/properties/{listing.slug}"
            if action_name in public_actions
            else f"/account/manage/properties/{listing.id}/edit"
        )
        action_labels = {
            "PROPERTY_APPROVED": "View listing",
            "PROPERTY_RESTORED": "View listing",
            "PROPERTY_CHANGES_REQUESTED": "Review changes",
            "PROPERTY_REJECTED": "View decision",
            "PROPERTY_SUSPENDED": "Open",
        }
        notify_transactional(
            listing.owner,
            NotificationType.LISTING_STATUS_UPDATE,
            f"Listing {label}",
            message,
            {
                "route": route,
                "action": action_name,
                "action_label": action_labels.get(action_name, "Open"),
                "status": listing.status,
                "property_id": str(listing.id),
                "property_slug": listing.slug,
            },
            f"property-moderation:{action_name}:{listing.id}:{listing.updated_at.isoformat()}",
            "email_enabled",
        )


@api_view(["POST"])
@permission_classes([permissions.IsAdminUser])
def listing_action(r, target_type, target_id, action_name):
    if target_type not in {"property", "stay"} or action_name not in {"suspend", "pause", "unpublish", "reinstate"}:
        raise NotFound()
    Model = (
        __import__("properties.models", fromlist=["PropertyListing"]).PropertyListing
        if target_type == "property"
        else __import__("stays.models", fromlist=["Stay"]).Stay
    )
    try:
        obj = Model.objects.get(pk=target_id)
    except Model.DoesNotExist:
        raise NotFound()
    reason = r.data.get("reason", "").strip()
    if action_name in {"suspend", "unpublish"} and not reason:
        raise ValidationError({"reason": "A reason is required."})
    obj.status = {"suspend": "SUSPENDED", "pause": "PAUSED", "unpublish": "PAUSED", "reinstate": "PUBLISHED"}[
        action_name
    ]
    obj.save()
    ModerationAuditEvent.objects.create(
        actor=r.user, action=f"LISTING_{action_name.upper()}", **{target_type: obj}, reason=reason
    )
    from notifications.models import NotificationType
    from notifications.services import notify_transactional

    notify_transactional(
        obj.owner,
        NotificationType.LISTING_STATUS_UPDATE,
        f"Listing {action_name}",
        f"Your listing was {action_name}d by moderation.",
        {"route": f"/{target_type}s/{obj.slug}"},
        f"moderation:{action_name}:{obj.id}",
        "email_enabled",
    )
    return Response({"status": obj.status})


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def summary(r):
    from verification.models import VerificationRequest, RequestStatus
    from properties.models import PropertyListing
    from stays.models import Stay

    return Response(
        {
            "pending_verification_requests": VerificationRequest.objects.filter(
                status__in=[RequestStatus.SUBMITTED, RequestStatus.UNDER_REVIEW]
            ).count(),
            "open_listing_reports": ListingReport.objects.filter(status="OPEN").count(),
            "reports_under_review": ListingReport.objects.filter(status="UNDER_REVIEW").count(),
            "suspended_listings": PropertyListing.objects.filter(status="SUSPENDED").count()
            + Stay.objects.filter(status="SUSPENDED").count(),
            "recent_moderation_activity": ModerationAuditEvent.objects.order_by("-created_at").values(
                "action", "created_at"
            )[:10],
        }
    )
