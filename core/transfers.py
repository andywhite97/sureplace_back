from contextlib import contextmanager
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from accounts.permissions import IsEmailVerified
from agencies.models import Agency
from properties.models import PropertyListing
from stays.models import Stay
from .models import ListingTransfer


def agency_admin(user, agency_id):
    return user.agent_profiles.filter(
        agency_id=agency_id, agency__is_active=True, is_active=True, role__in=["OWNER", "ADMIN"]
    ).exists()


def can_send(user, listing):
    return agency_admin(user, listing.agency_id) if listing.agency_id else listing.owner_id == user.pk


def can_receive(user, transfer):
    return (
        agency_admin(user, transfer.target_agency_id) if transfer.target_agency_id else transfer.recipient_id == user.pk
    )


def listing_model(kind):
    return PropertyListing if kind == "property" else Stay


@contextmanager
def locked_listing(listing):
    if isinstance(listing, PropertyListing):
        from properties.entitlements import lock_listing_owners

        with lock_listing_owners(listing) as current:
            yield current
    else:
        from stays.entitlements import lock_stay_owners

        with lock_stay_owners(listing) as (current, _):
            yield current


def data(transfer, user):
    return {
        "id": str(transfer.id),
        "kind": transfer.kind,
        "listing_id": str(transfer.listing_id),
        "listing_title": transfer.listing_title,
        "sender": transfer.sender.email,
        "recipient": transfer.target_agency.name if transfer.target_agency_id else transfer.recipient.email,
        "status": (
            "EXPIRED" if transfer.status == "PENDING" and transfer.expires_at <= timezone.now() else transfer.status
        ),
        "expires_at": transfer.expires_at,
        "created_at": transfer.created_at,
        "can_receive": can_receive(user, transfer),
        "can_cancel": transfer.sender_id == user.pk,
    }


class TransferInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["property", "stay"])
    listing_id = serializers.UUIDField()
    email = serializers.EmailField(required=False)
    agency_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if ("email" in attrs) == ("agency_id" in attrs):
            raise serializers.ValidationError("Choose a user email or an agency.")
        return attrs


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsEmailVerified])
def transfers(request):
    if request.method == "GET":
        admin_agencies = request.user.agent_profiles.filter(
            is_active=True, agency__is_active=True, role__in=["OWNER", "ADMIN"]
        ).values("agency_id")
        items = ListingTransfer.objects.filter(
            Q(sender=request.user) | Q(recipient=request.user) | Q(target_agency_id__in=admin_agencies)
        ).select_related("sender", "recipient", "target_agency")
        return Response([data(item, request.user) for item in items[:200]])
    serializer = TransferInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    attrs = serializer.validated_data
    listing = get_object_or_404(listing_model(attrs["kind"]), pk=attrs["listing_id"])
    with transaction.atomic(), locked_listing(listing) as listing:
        if not can_send(request.user, listing):
            raise PermissionDenied("Only the owner or an agency owner/admin can transfer this listing.")
        recipient = None
        agency = None
        if "email" in attrs:
            recipient = get_user_model().objects.filter(email__iexact=attrs["email"], is_active=True).first()
            if not recipient:
                raise ValidationError("The recipient must have an active SurePlace account.")
            if not listing.agency_id and recipient.pk == listing.owner_id:
                raise ValidationError("This user already owns the listing.")
        else:
            agency = get_object_or_404(Agency, pk=attrs["agency_id"], is_active=True)
            if agency.pk == listing.agency_id:
                raise ValidationError("This agency already manages the listing.")
            if not agency.agents.filter(is_active=True, user__is_active=True, role__in=["OWNER", "ADMIN"]).exists():
                raise ValidationError("This agency has no active owner or admin to accept the transfer.")
        ListingTransfer.objects.filter(
            kind=attrs["kind"], listing_id=listing.pk, status="PENDING", expires_at__lte=timezone.now()
        ).update(status="CANCELLED", resolved_at=timezone.now())
        if ListingTransfer.objects.filter(kind=attrs["kind"], listing_id=listing.pk, status="PENDING").exists():
            raise ValidationError("Cancel the pending transfer before sending another.")
        transfer = ListingTransfer.objects.create(
            kind=attrs["kind"],
            listing_id=listing.pk,
            listing_title=getattr(listing, "title", None) or listing.name,
            sender=request.user,
            source_owner_id=listing.owner_id,
            source_agency_id=listing.agency_id,
            recipient=recipient,
            target_agency=agency,
            expires_at=timezone.now() + timedelta(days=7),
        )
        from notifications.services import create_notification

        recipients = (
            [recipient]
            if recipient
            else get_user_model()
            .objects.filter(
                agent_profiles__agency=agency,
                agent_profiles__is_active=True,
                agent_profiles__role__in=["OWNER", "ADMIN"],
                is_active=True,
            )
            .distinct()
        )
        for user in recipients:
            create_notification(
                user,
                "SYSTEM",
                "Listing transfer request",
                f"{request.user.email} wants to transfer {transfer.listing_title} to you. Review it within 7 days.",
                {"route": "/account/transfers"},
                event_key=f"transfer:{transfer.pk}:requested:{user.pk}",
            )
    return Response(data(transfer, request.user), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsEmailVerified])
def transfer_options(request):
    agency_ids = request.user.agent_profiles.filter(
        is_active=True, agency__is_active=True, role__in=["OWNER", "ADMIN"]
    ).values("agency_id")
    scope = Q(owner=request.user, agency__isnull=True) | Q(agency_id__in=agency_ids)
    listings = []
    for kind, model in [("property", PropertyListing), ("stay", Stay)]:
        for item in model.objects.filter(scope):
            listings.append(
                {
                    "id": str(item.pk),
                    "kind": kind,
                    "title": getattr(item, "title", None) or item.name,
                    "public_id": item.public_id,
                }
            )
    return Response(
        {"listings": listings, "agencies": list(Agency.objects.filter(is_active=True).values("id", "name"))}
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsEmailVerified])
def resolve_transfer(request, transfer_id):
    action = request.data.get("action")
    if action not in ["accept", "decline", "cancel"]:
        raise ValidationError("Choose accept, decline or cancel.")
    with transaction.atomic():
        transfer = get_object_or_404(ListingTransfer.objects.select_for_update(), pk=transfer_id)
        if action == "cancel":
            if transfer.sender_id != request.user.pk:
                raise PermissionDenied()
        elif not can_receive(request.user, transfer):
            raise PermissionDenied()
        if transfer.status != "PENDING" or transfer.expires_at <= timezone.now():
            raise ValidationError("This transfer is no longer pending or has expired.")
        if action == "accept":
            listing = get_object_or_404(listing_model(transfer.kind), pk=transfer.listing_id)
            # Destination scope must be locked as well as the original scope.
            listing.owner = request.user
            listing.agency_id = transfer.target_agency_id
            listing.agent = None
            try:
                with locked_listing(listing) as current:
                    if (
                        (current.owner_id, current.agency_id) != (transfer.source_owner_id, transfer.source_agency_id)
                        or not can_send(transfer.sender, current)
                        or not transfer.sender.is_active
                    ):
                        raise ValidationError(
                            "Ownership or sender access changed. Ask the current owner to send a new request."
                        )
                    current.owner = request.user
                    current.agency_id = transfer.target_agency_id
                    current.agent = None
                    current.verification_status = "UNVERIFIED"
                    current.save(update_fields=["owner", "agency", "agent", "verification_status", "updated_at"])
            except ModelValidationError as exc:
                raise ValidationError(exc.messages) from exc
        transfer.status = {"accept": "ACCEPTED", "decline": "DECLINED", "cancel": "CANCELLED"}[action]
        transfer.resolved_at = timezone.now()
        transfer.resolved_by = request.user
        transfer.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
        from notifications.services import create_notification

        create_notification(
            transfer.sender,
            "SYSTEM",
            "Listing transfer updated",
            f"{transfer.listing_title}: {transfer.status.lower()}.",
            {"route": "/account/transfers"},
            event_key=f"transfer:{transfer.pk}:{transfer.status}",
        )
        return Response(data(transfer, request.user))


urlpatterns = [
    path("listing-transfers/", transfers),
    path("listing-transfers/options/", transfer_options),
    path("listing-transfers/<uuid:transfer_id>/", resolve_transfer),
]
