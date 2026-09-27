from django.http import FileResponse
from django.db.models import Q
from django.utils import timezone
from django.db import transaction
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from accounts.permissions import IsEmailVerified
from .models import *
from .serializers import *
from .services import ModerationConflict, authorized, review, submit, suspend


class CanReviewVerification(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.has_perm("verification.review_verificationrequest"))
        )


class RequestViewSet(viewsets.ModelViewSet):
    serializer_class = RequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsEmailVerified]

    def get_queryset(self):
        return VerificationRequest.objects.filter(applicant=self.request.user).select_related(
            "agency", "agent_profile", "property", "stay"
        ).prefetch_related("documents").order_by("-created_at")

    def perform_create(self, s):
        s.save(applicant=self.request.user)

    def perform_update(self, s):
        if s.instance.status not in (RequestStatus.DRAFT, RequestStatus.CHANGES_REQUESTED):
            raise ValidationError("Only draft or changes-requested requests can be edited.")
        s.save()

    @action(detail=False, methods=["get"])
    def eligible(self, request):
        """Minimal, permission-filtered entities for the verification wizard."""
        from agencies.models import AgentProfile, Agency
        from properties.models import PropertyListing
        from stays.models import Stay
        user = request.user
        agencies = Agency.objects.filter(agents__user=user, agents__is_active=True).distinct()
        properties = PropertyListing.objects.filter(
            Q(owner=user) | Q(agent__user=user, agent__is_active=True) | Q(agency__in=agencies)
        ).distinct()
        stays = Stay.objects.filter(
            Q(owner=user) | Q(agent__user=user, agent__is_active=True) | Q(agency__in=agencies)
        ).distinct()
        return Response({
            "agencies": [{"id": str(a.id), "name": a.name} for a in agencies],
            "agents": [{"id": str(a.id), "name": str(a)} for a in AgentProfile.objects.filter(user=user, is_active=True)],
            "properties": [{"id": str(p.id), "name": p.title, "public_id": p.public_id} for p in properties],
            "stays": [{"id": str(s.id), "name": s.name, "public_id": s.public_id} for s in stays],
        })

    @action(detail=True, methods=["post"])
    def submit(self, r, pk=None):
        try:
            o = submit(self.get_object(), r.user)
        except Exception as e:
            raise ValidationError(getattr(e, "messages", str(e)))
        return Response(self.get_serializer(o).data)

    @action(detail=True, methods=["post"])
    def cancel(self, r, pk=None):
        o = self.get_object()
        if o.status not in (RequestStatus.DRAFT, RequestStatus.SUBMITTED):
            raise ValidationError("Request cannot be cancelled.")
        o.status = RequestStatus.CANCELLED
        o.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(o).data)

    @action(detail=True, methods=["post"])
    def documents(self, r, pk=None):
        request = self.get_object()
        if request.status not in (RequestStatus.DRAFT, RequestStatus.CHANGES_REQUESTED):
            raise ValidationError("Documents can only be added to draft or changes-requested requests.")
        s = DocumentSerializer(data=r.data)
        s.is_valid(raise_exception=True)
        return Response(DocumentSerializer(s.save(verification_request=request)).data, status=201)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def types(r):
    from .requirements import definitions
    return Response(definitions())


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def download_document(r, document_id):
    d = VerificationDocument.objects.select_related("verification_request").get(pk=document_id)
    request = d.verification_request
    if (
        not authorized(r.user, request)
        and not r.user.has_perm("verification.review_verificationrequest")
        and not r.user.is_superuser
    ):
        raise PermissionDenied()
    return FileResponse(d.file.open("rb"), as_attachment=True, filename=d.file.name.rsplit("/", 1)[-1])


@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated, IsEmailVerified])
def delete_document(r, document_id):
    d = VerificationDocument.objects.select_related("verification_request").get(pk=document_id)
    if not authorized(r.user, d.verification_request):
        raise PermissionDenied()
    if d.verification_request.status not in (RequestStatus.DRAFT, RequestStatus.CHANGES_REQUESTED):
        raise ValidationError("Documents can only be deleted from draft or changes-requested requests.")
    d.file.delete(save=False)
    d.delete()
    return Response(status=204)


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VerificationRequest.objects.select_related(
        "applicant", "agency", "agent_profile", "property", "stay"
    ).prefetch_related("documents").order_by("-created_at")
    serializer_class = RequestSerializer
    permission_classes = [CanReviewVerification]

    @action(detail=True, methods=["post"], url_path="start-review")
    def start(self, r, pk=None):
        return Response(self.get_serializer(review(self.get_object(), r.user, RequestStatus.UNDER_REVIEW)).data)

    @action(detail=True, methods=["post"])
    def approve(self, r, pk=None):
        return Response(
            self.get_serializer(review(self.get_object(), r.user, RequestStatus.APPROVED, r.data.get("notes", ""))).data
        )

    @action(detail=True, methods=["post"])
    def reject(self, r, pk=None):
        notes = str(r.data.get("notes", "")).strip()
        if not notes:
            raise ValidationError({"notes": "A rejection reason is required."})
        return Response(
            self.get_serializer(review(self.get_object(), r.user, RequestStatus.REJECTED, notes)).data
        )

    @action(detail=True, methods=["post"], url_path=r"documents/(?P<document_id>[^/.]+)/reject")
    @transaction.atomic
    def reject_document(self, r, pk=None, document_id=None):
        request = VerificationRequest.objects.select_for_update().get(pk=pk)
        if request.status not in (RequestStatus.SUBMITTED, RequestStatus.UNDER_REVIEW):
            raise ModerationConflict()
        notes = str(r.data.get("notes", "")).strip()
        if not notes:
            raise ValidationError({"notes": "A document rejection reason is required."})
        try:
            document = request.documents.select_for_update().get(pk=document_id)
        except VerificationDocument.DoesNotExist:
            raise ValidationError({"document": "This document does not belong to the verification request."})
        if document.status == DocumentStatus.REJECTED:
            raise ValidationError({"document": "This document has already been rejected."})

        old = request.status
        document.status = DocumentStatus.REJECTED
        document.rejection_reason = notes
        document.reviewed_by = r.user
        document.reviewed_at = timezone.now()
        document.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])
        request.status = RequestStatus.CHANGES_REQUESTED
        request.reviewer_notes = notes
        request.requirement_notes = {}
        request.save(update_fields=["status", "reviewer_notes", "requirement_notes", "updated_at"])
        from .services import audit
        audit(request, r.user, "DOCUMENT_REJECTED", old, notes)
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        notify_transactional(
            request.applicant,
            NotificationType.VERIFICATION_UPDATE,
            "Verification document rejected",
            f"A document needs replacing: {notes}",
            {"route": f"/account/verification/{request.id}"},
            f"verification:DOCUMENT_REJECTED:{document.id}",
            "email_enabled",
        )
        # The review queryset prefetches documents. Clear that cache before serializing so the
        # client receives the document's new status without needing a page reload.
        request.refresh_from_db()
        return Response(self.get_serializer(request).data)

    @action(detail=True, methods=["post"], url_path="request-changes")
    @transaction.atomic
    def request_changes(self, r, pk=None):
        request = VerificationRequest.objects.select_for_update().get(pk=pk)
        if request.status not in (RequestStatus.SUBMITTED, RequestStatus.UNDER_REVIEW):
            raise ModerationConflict()
        notes = str(r.data.get("notes", "")).strip()
        keys = r.data.get("requirement_keys", [])
        if not notes or not isinstance(keys, list) or not keys:
            raise ValidationError({"notes": "Notes and at least one requirement are required."})
        from .requirements import DEFINITIONS

        definition = DEFINITIONS.get(request.verification_type, {})
        document_types = set()
        valid_keys = set()
        for requirement in definition.get("requirements", []):
            valid_keys.add(requirement["key"])
            alternatives = set(requirement.get("alternatives", [requirement["key"]]))
            valid_keys.update(alternatives)
            if requirement["key"] in keys or alternatives.intersection(keys):
                document_types.update(alternatives)
        unknown = set(keys) - valid_keys
        if unknown:
            raise ValidationError({"requirement_keys": f"Unknown requirements: {sorted(unknown)}"})

        old = request.status
        request.status = RequestStatus.CHANGES_REQUESTED
        request.reviewer_notes = notes
        request.requirement_notes = {
            requirement["key"]: notes
            for requirement in definition.get("requirements", [])
            if requirement["key"] in keys
            or set(requirement.get("alternatives", [requirement["key"]])).intersection(keys)
        }
        request.save(update_fields=["status", "reviewer_notes", "requirement_notes", "updated_at"])
        request.documents.filter(document_type__in=document_types).update(
            status=DocumentStatus.REJECTED, rejection_reason=notes
        )
        from .services import audit
        audit(request, r.user, "CHANGES_REQUESTED", old, notes)
        from notifications.models import NotificationType
        from notifications.services import notify_transactional

        notify_transactional(
            request.applicant,
            NotificationType.VERIFICATION_UPDATE,
            "Verification changes requested",
            notes,
            {"route": "/account/verification"},
            f"verification:CHANGES_REQUESTED:{request.id}",
            "email_enabled",
        )
        request.refresh_from_db()
        request._prefetched_objects_cache = {}
        return Response(self.get_serializer(request).data)

    @action(detail=True, methods=["post"])
    def suspend(self, r, pk=None):
        return Response(self.get_serializer(suspend(self.get_object(), r.user, r.data.get("reason", ""))).data)
