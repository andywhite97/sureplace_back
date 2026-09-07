from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from .models import ListingReport, ModerationAuditEvent
from .serializers import ReportSerializer


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
