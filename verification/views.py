from django.http import FileResponse
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .models import *
from .serializers import *
from .services import authorized, review, submit, suspend


class CanReviewVerification(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.has_perm("verification.review_verificationrequest"))
        )


class RequestViewSet(viewsets.ModelViewSet):
    serializer_class = RequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return VerificationRequest.objects.filter(applicant=self.request.user).select_related(
            "agency", "agent_profile", "property", "stay"
        )

    def perform_create(self, s):
        s.save(applicant=self.request.user)

    def perform_update(self, s):
        if s.instance.status != RequestStatus.DRAFT:
            raise ValidationError("Only draft requests can be edited.")
        s.save()

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
        if request.status != RequestStatus.DRAFT:
            raise ValidationError("Documents can only be added to draft requests.")
        s = DocumentSerializer(data=r.data)
        s.is_valid(raise_exception=True)
        return Response(DocumentSerializer(s.save(verification_request=request)).data, status=201)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def types(r):
    return Response(
        [
            {
                "type": v,
                "label": l,
                "description": f"SurePlace checks supporting evidence for {l.lower()}.",
                "disclaimer": "Verification does not guarantee a transaction.",
            }
            for v, l in VerificationType.choices
        ]
    )


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
@permission_classes([permissions.IsAuthenticated])
def delete_document(r, document_id):
    d = VerificationDocument.objects.select_related("verification_request").get(pk=document_id)
    if not authorized(r.user, d.verification_request):
        raise PermissionDenied()
    if d.verification_request.status != RequestStatus.DRAFT:
        raise ValidationError("Documents can only be deleted from draft requests.")
    d.file.delete(save=False)
    d.delete()
    return Response(status=204)


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VerificationRequest.objects.all()
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
        return Response(
            self.get_serializer(review(self.get_object(), r.user, RequestStatus.REJECTED, r.data.get("notes", ""))).data
        )

    @action(detail=True, methods=["post"])
    def suspend(self, r, pk=None):
        return Response(self.get_serializer(suspend(self.get_object(), r.user, r.data.get("reason", ""))).data)
