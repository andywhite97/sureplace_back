"""Isolated prospect staging. Every mutation locks the prospect and checks its version."""

import base64
import hashlib
import io
import json
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import include, path
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from .onboarding_models import (
    OnboardingProspect as Prospect,
    OnboardingPreview as Preview,
    OnboardingImage,
    OnboardingAudit,
)


class Conflict(APIException):
    status_code = 409
    default_detail = "This prospect changed. Reload before continuing."


COMMON = {
    "description",
    "region",
    "town",
    "suburb",
    "address",
    "latitude",
    "longitude",
    "website",
    "whatsapp_number",
    "facebook_url",
    "instagram_url",
    "tiktok_url",
}
STAY = COMMON | {"name", "stay_type", "house_rules", "cancellation_policy", "check_in_time", "check_out_time"}
PROPERTY = COMMON | {
    "title",
    "listing_type",
    "property_type",
    "price",
    "currency",
    "bedrooms",
    "bathrooms",
    "parking_spaces",
    "floor_area",
    "land_area",
    "furnished",
    "pet_friendly",
}
ROOM = {
    "name",
    "description",
    "capacity_adults",
    "capacity_children",
    "total_capacity",
    "number_of_beds",
    "bed_configuration",
    "bathroom_type",
    "quantity",
    "base_price",
    "currency",
    "minimum_stay",
}


def validate_payload(value, kind):
    allowed = STAY | {"room_types"} if kind == "STAY" else PROPERTY
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValidationError(
            {"draft_payload": "Only listing content fields are allowed; ownership and publication cannot be supplied."}
        )
    if len(json.dumps(value)) > 40000:
        raise ValidationError({"draft_payload": "Preview content is too large."})
    rooms = value.get("room_types", [])
    if not isinstance(rooms, list) or len(rooms) > 20 or any(not isinstance(r, dict) or set(r) - ROOM for r in rooms):
        raise ValidationError({"draft_payload": "Invalid room content."})
    # Validate supplied values through established field validators; incomplete previews are allowed.
    from stays.serializers import StayWriteSerializer, RoomWriteSerializer
    from properties.serializers import PropertyWriteSerializer

    schema = StayWriteSerializer() if kind == "STAY" else PropertyWriteSerializer()
    for key, raw in value.items():
        if key != "room_types":
            schema.fields[key].run_validation(raw)
    for room in rooms:
        for key, raw in room.items():
            RoomWriteSerializer().fields[key].run_validation(raw)
    return value


class ProspectSerializer(serializers.ModelSerializer):
    images = serializers.SerializerMethodField()
    audit = serializers.SerializerMethodField()

    class Meta:
        model = Prospect
        exclude = ("approved_hash",)
        read_only_fields = (
            "status",
            "version",
            "approved_version",
            "approved_by",
            "approved_at",
            "approval_evidence",
            "claim_user",
            "claim_agency",
            "claim_expires_at",
            "resulting_stay",
            "resulting_property",
            "created_at",
            "updated_at",
        )

    def get_images(self, obj):
        return list(obj.images.values("id", "caption", "source", "permission_evidence"))

    def get_audit(self, obj):
        return list(obj.audit.values("id", "actor", "action", "version", "evidence", "created_at")[:100])

    def validate_assigned_staff(self, value):
        if value and (not value.is_active or not value.is_staff):
            raise ValidationError("Choose an active staff member.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", "STAY"))
        if self.instance and kind != self.instance.kind:
            raise ValidationError("Create a separate prospect to change listing type.")
        if "draft_payload" in attrs:
            validate_payload(attrs["draft_payload"], kind)
        if (
            attrs.get("consent_status") in ("GRANTED", "WITHDRAWN")
            and not attrs.get("consent_evidence", getattr(self.instance, "consent_evidence", "")).strip()
        ):
            raise ValidationError({"consent_evidence": "Record how consent was obtained or withdrawn."})
        return attrs


def audit(p, user, action, **evidence):
    OnboardingAudit.objects.create(prospect=p, actor=user, action=action, version=p.version, evidence=evidence)


def invalidate(p):
    p.version += 1
    p.approved_version = None
    p.approved_hash = ""
    p.approved_by = None
    p.approved_at = None
    p.approval_evidence = ""
    p.claim_user = None
    p.claim_agency = None
    p.claim_expires_at = None
    p.previews.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    p.status = "CONTENT_GATHERING"


def snapshot_hash(p):
    value = {
        "kind": p.kind,
        "business_name": p.business_name,
        "payload": p.draft_payload,
        "source": p.source_evidence,
        "images": [
            (str(i.id), hashlib.sha256(bytes(i.content)).hexdigest(), i.caption, i.source, i.permission_evidence)
            for i in p.images.order_by("id")
        ],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class StaffPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        action_name = getattr(view, "action", "")
        key = {
            "list": "view_onboardingprospect",
            "retrieve": "view_onboardingprospect",
            "create": "add_onboardingprospect",
            "destroy": "delete_onboardingprospect",
            "issue": "issue_onboarding",
            "revoke": "issue_onboarding",
            "approve": "approve_onboarding",
            "invite": "handoff_onboarding",
        }.get(action_name, "change_onboardingprospect")
        return bool(
            user.is_authenticated
            and user.is_staff
            and user.has_perm("core.view_onboardingprospect")
            and user.has_perm("core." + key)
        )


class PrivateResponseMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response["Referrer-Policy"] = "no-referrer"
        return response


class ProspectViewSet(PrivateResponseMixin, viewsets.ModelViewSet):
    permission_classes = [StaffPermission]
    serializer_class = ProspectSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Prospect.objects.all()
        for key in ("kind", "town", "status"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        if self.request.query_params.get("search"):
            qs = qs.filter(business_name__icontains=self.request.query_params["search"])
        return qs

    def locked(self):
        p = get_object_or_404(Prospect.objects.select_for_update(), pk=self.kwargs["pk"])
        if str(self.request.data.get("version")) != str(p.version):
            raise Conflict()
        if p.status in ("HANDED_OFF", "CLOSED"):
            raise Conflict("This prospect is closed to changes.")
        return p

    @transaction.atomic
    def perform_create(self, serializer):
        p = serializer.save()
        audit(p, self.request.user, "CREATED", consent=p.consent_status, evidence=p.consent_evidence)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        p = self.locked()
        serializer = self.get_serializer(p, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        previous = p.consent_status
        invalidate(p)
        p = serializer.save()
        audit(
            p,
            request.user,
            "REVISED",
            previous_consent=previous,
            consent=p.consent_status,
            evidence=p.consent_evidence,
            snapshot=snapshot_hash(p),
        )
        return Response(self.get_serializer(p).data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        p = get_object_or_404(Prospect.objects.select_for_update(), pk=self.kwargs["pk"])
        if str(request.data.get("version", request.query_params.get("version"))) != str(p.version):
            raise Conflict()
        if p.status != "CLOSED" or p.resulting_stay_id or p.resulting_property_id:
            raise Conflict("Only closed unused prospects can be deleted.")
        p.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def prepare(self, request, pk=None):
        p = self.locked()
        if p.consent_status != "GRANTED" or not p.source_evidence.strip() or not p.draft_payload.get("description"):
            raise ValidationError("Record content permission, source evidence and a description first.")
        p.status = "PREVIEW_READY"
        p.save()
        audit(p, request.user, "PREPARED", snapshot=snapshot_hash(p))
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def issue(self, request, pk=None):
        p = self.locked()
        if p.consent_status != "GRANTED" or p.status not in (
            "PREVIEW_READY",
            "PREVIEW_SENT",
            "APPROVED",
            "CLAIM_PENDING",
        ):
            raise ValidationError("Prepare a consented preview first.")
        p.previews.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        token = secrets.token_urlsafe(32)
        preview = Preview.objects.create(
            prospect=p,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            version=p.version,
            expires_at=timezone.now() + timedelta(days=7),
        )
        audit(p, request.user, "LINK_ISSUED", expires_at=preview.expires_at.isoformat())
        return Response({"token": token, "expires_at": preview.expires_at, "version": p.version})

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def revoke(self, request, pk=None):
        p = self.locked()
        p.previews.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        audit(p, request.user, "LINK_REVOKED")
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def transition(self, request, pk=None):
        p = self.locked()
        target = request.data.get("status")
        evidence = str(request.data.get("evidence", "")).strip()
        if target not in ("PREVIEW_SENT", "CHANGES_REQUESTED", "CLOSED") or not evidence:
            raise ValidationError("Choose a status and record what happened.")
        if target == "PREVIEW_SENT" and p.status != "PREVIEW_READY":
            raise Conflict("Prepare the preview before recording delivery.")
        if target in ("CHANGES_REQUESTED", "CLOSED"):
            invalidate(p)
        p.status = target
        if target == "PREVIEW_SENT":
            p.last_contacted_at = timezone.now()
        p.save()
        audit(p, request.user, target, evidence=evidence)
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        p = self.locked()
        evidence = str(request.data.get("evidence", "")).strip()
        if (
            p.consent_status != "GRANTED"
            or p.status not in ("PREVIEW_READY", "PREVIEW_SENT")
            or len(evidence) < 20
            or request.data.get("rights_confirmed") is not True
        ):
            raise ValidationError(
                "Record signed approval or independently verified owner confirmation, identity verification method, and listing/photo rights for this version."
            )
        p.approved_version = p.version
        p.approved_hash = snapshot_hash(p)
        p.approved_by = request.user
        p.approved_at = timezone.now()
        p.approval_evidence = evidence
        p.status = "APPROVED"
        p.save()
        audit(p, request.user, "APPROVED", evidence=evidence, rights_confirmed=True, snapshot=p.approved_hash)
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def invite(self, request, pk=None):
        p = self.locked()
        evidence = str(request.data.get("evidence", "")).strip()
        if p.approved_version != p.version or p.approved_hash != snapshot_hash(p) or p.consent_status != "GRANTED":
            raise Conflict("Current content needs approval.")
        if len(evidence) < 20:
            raise ValidationError("Record independent identity and ownership checks before binding the invitation.")
        user = (
            get_user_model()
            .objects.filter(email__iexact=p.contact_email, is_active=True, is_email_verified=True)
            .first()
        )
        if not user:
            raise ValidationError(
                "Ask the prospect to register and verify their contact email first. No invitation was sent."
            )
        agency = request.data.get("agency")
        if (
            agency
            and not user.agent_profiles.filter(agency_id=agency, is_active=True, role__in=["OWNER", "ADMIN"]).exists()
        ):
            raise PermissionDenied("The recipient must be an owner or administrator of this agency.")
        p.claim_user = user
        p.claim_agency_id = agency or None
        p.claim_expires_at = timezone.now() + timedelta(days=7)
        p.status = "CLAIM_PENDING"
        p.save()
        audit(p, request.user, "CLAIM_BOUND", recipient=str(user.id), agency=agency, evidence=evidence)
        return Response(self.get_serializer(p).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def image(self, request, pk=None):
        p = self.locked()
        if request.data.get("remove"):
            get_object_or_404(p.images, pk=request.data["remove"]).delete()
        else:
            upload = request.FILES.get("image")
            source = str(request.data.get("source", "")).strip()
            evidence = str(request.data.get("permission_evidence", "")).strip()
            if not upload or upload.size > 5 * 1024 * 1024 or not source or not evidence or p.images.count() >= 12:
                raise ValidationError("Upload up to 12 images, at most 5 MB each, with source and permission evidence.")
            try:
                with Image.open(upload) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP") or image.width * image.height > 20000000:
                        raise ValueError()
                    image.thumbnail((1600, 1600))
                    out = io.BytesIO()
                    image.convert("RGB").save(out, format="JPEG", quality=85)
            except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise ValidationError("Invalid or oversized image.")
            OnboardingImage.objects.create(
                prospect=p,
                content=out.getvalue(),
                source=source[:1000],
                permission_evidence=evidence,
                caption=str(request.data.get("caption", ""))[:255],
            )
        invalidate(p)
        p.save()
        audit(p, request.user, "IMAGES_REVISED", snapshot=snapshot_hash(p))
        return Response(self.get_serializer(p).data)


class PreviewThrottle(SimpleRateThrottle):
    scope = "onboarding_preview"
    rate = "30/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class PreviewView(PrivateResponseMixin, APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PreviewThrottle]

    def post(self, request):
        token = request.data.get("token", "")
        if not isinstance(token, str) or not 40 <= len(token) <= 64:
            raise NotFound()
        preview = (
            Preview.objects.select_related("prospect")
            .filter(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if not preview:
            raise NotFound()
        p = preview.prospect
        if preview.version != p.version or p.consent_status != "GRANTED" or p.status in ("CLOSED", "HANDED_OFF"):
            raise NotFound()
        return Response(
            {
                "business_name": p.business_name,
                "kind": p.kind,
                "version": p.version,
                "content": p.draft_payload,
                "images": [
                    {
                        "id": str(i.id),
                        "caption": i.caption,
                        "data": "data:image/jpeg;base64," + base64.b64encode(bytes(i.content)).decode(),
                    }
                    for i in p.images.all()
                ],
                "notice": "Private preview — not yet published. Prices, amenities and availability are indicative and not confirmed. Contact your SurePlace representative to request changes.",
            }
        )


class ClaimView(PrivateResponseMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        p = get_object_or_404(Prospect, pk=pk, claim_user=request.user)
        if p.status != "HANDED_OFF" and (not p.claim_expires_at or p.claim_expires_at <= timezone.now()):
            raise NotFound()
        return Response(
            {
                "id": p.id,
                "business_name": p.business_name,
                "kind": p.kind,
                "version": p.version,
                "status": p.status,
                "content": p.draft_payload,
                "agency": str(p.claim_agency_id) if p.claim_agency_id else None,
                "images": [
                    {
                        "id": str(i.id),
                        "caption": i.caption,
                        "data": "data:image/jpeg;base64," + base64.b64encode(bytes(i.content)).decode(),
                    }
                    for i in p.images.all()
                ],
            }
        )

    @transaction.atomic
    def post(self, request, pk):
        p = get_object_or_404(Prospect.objects.select_for_update(), pk=pk, claim_user=request.user)
        if p.status == "HANDED_OFF":
            return Response(
                {
                    "kind": p.kind,
                    "listing_id": p.resulting_stay_id or p.resulting_property_id,
                    "status": "DRAFT_CREATED",
                }
            )
        if (
            p.status != "CLAIM_PENDING"
            or not p.claim_expires_at
            or p.claim_expires_at <= timezone.now()
            or p.version != request.data.get("version")
            or p.approved_version != p.version
            or p.approved_hash != snapshot_hash(p)
            or p.consent_status != "GRANTED"
        ):
            raise Conflict("This invitation expired or its content changed.")
        if not request.user.is_email_verified or request.user.email.lower() != p.contact_email.lower():
            raise PermissionDenied("Verify the invited contact email.")
        if request.data.get("accept_rights") is not True:
            raise ValidationError("Explicitly confirm your right to manage this listing and its content.")
        if (
            p.claim_agency_id
            and not request.user.agent_profiles.filter(
                agency_id=p.claim_agency_id, is_active=True, role__in=["OWNER", "ADMIN"]
            ).exists()
        ):
            raise PermissionDenied()
        from stays.serializers import StayWriteSerializer, RoomWriteSerializer
        from properties.serializers import PropertyWriteSerializer

        payload = dict(p.draft_payload)
        rooms = payload.pop("room_types", [])
        validate_payload(p.draft_payload, p.kind)
        if p.claim_agency_id:
            payload["agency"] = str(p.claim_agency_id)
        serializer_class = StayWriteSerializer if p.kind == "STAY" else PropertyWriteSerializer
        serializer = serializer_class(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        listing = serializer.save()
        if listing.status != "DRAFT":
            raise Conflict("Handoff must create a draft.")
        if p.kind == "STAY":
            for room in rooms:
                rs = RoomWriteSerializer(data=room, context={"stay": listing})
                rs.is_valid(raise_exception=True)
                rs.save(stay=listing, is_active=False)
            p.resulting_stay = listing
        else:
            p.resulting_property = listing
        # Copy only after the verified owner explicitly opts into ordinary listing media.
        # Until then, staging images have no public storage URLs.
        uploaded = []
        if request.data.get("use_approved_photos") is True:
            from django.core.files.base import ContentFile
            from stays.serializers import ImageSerializer
            from properties.serializers import PropertyImageSerializer

            image_serializer = ImageSerializer if p.kind == "STAY" else PropertyImageSerializer
            try:
                for index, image in enumerate(p.images.order_by("created_at")):
                    content = ContentFile(bytes(image.content), name=f"{image.id}.jpg")
                    image_write = image_serializer(
                        data={"image": content, "caption": image.caption, "sort_order": index, "is_cover": index == 0}
                    )
                    image_write.is_valid(raise_exception=True)
                    uploaded.append(image_write.save(**{("stay" if p.kind == "STAY" else "property"): listing}))
            except Exception:
                for image in uploaded:
                    try:
                        image.image.delete(save=False)
                    except Exception:
                        pass  # Do not mask the original storage failure.
                raise
        p.status = "HANDED_OFF"
        p.previews.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        p.save()
        audit(
            p,
            request.user,
            "HANDED_OFF",
            listing=str(listing.id),
            rights_accepted=True,
            listing_photos_authorized=request.data.get("use_approved_photos") is True,
            images_copied=len(uploaded),
        )
        return Response({"kind": p.kind, "listing_id": listing.id, "status": "DRAFT_CREATED"})


router = DefaultRouter()
router.register("staff/onboarding", ProspectViewSet, basename="onboarding")
urlpatterns = [
    path("", include(router.urls)),
    path("onboarding/preview/", PreviewView.as_view()),
    path("onboarding/claims/<uuid:pk>/", ClaimView.as_view()),
]
