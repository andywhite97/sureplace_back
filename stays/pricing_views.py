import uuid
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response
from .models import Stay, StayPlan, StayAddOnPackage, StayPromotion
from .services import can_manage
from .entitlements import summary
from properties.entitlements import resolve_scope


@api_view(["GET"])
@permission_classes([AllowAny])
def stay_pricing(request):
    plans = list(
        StayPlan.objects.filter(is_active=True).values(
            "code", "display_name", "price", "billing_interval", "active_listing_limit"
        )
    )
    addons = list(
        StayAddOnPackage.objects.filter(is_active=True).values(
            "code", "display_name", "price", "quantity", "duration_days", "purchase_validity_days"
        )
    )
    promotions = list(
        StayPromotion.objects.filter(is_active=True).values("code", "display_name", "price", "duration_days")
    )
    for item in plans + addons + promotions:
        item["price"] = str(item["price"])
    for promotion in promotions:
        promotion.update(
            checkout_available=False,
            operational=False,
            description="Promotional visibility product coming soon. This does not add stay listing capacity.",
        )
    return Response(
        {
            "currency": "SZL",
            "currency_symbol": "E",
            "checkout_available": False,
            "plans": plans,
            "addons": addons,
            "promotions": promotions,
            "booking_commission_percent": 0,
            "features": [
                "Stay listing management",
                "Image galleries",
                "Room type management",
                "Room availability calendars",
                "Nightly pricing configuration",
                "Guest enquiries",
                "Booking requests",
                "Booking management",
                "Messaging",
                "Verification workflows",
                "Booking notifications",
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stay_entitlements(request):
    stay_id = request.query_params.get("stay")
    agency_id = request.query_params.get("agency")
    if stay_id:
        try:
            stay_id = uuid.UUID(stay_id)
        except ValueError:
            raise ValidationError({"stay": "A valid stay UUID is required."})
        stay = get_object_or_404(Stay, pk=stay_id)
        if not can_manage(request.user, stay):
            raise PermissionDenied("You cannot inspect this stay's entitlements.")
        if agency_id and str(stay.agency_id) != agency_id:
            raise ValidationError({"agency": "Stay and entitlement scope do not match."})
        account, agency = (None, stay.agency_id) if stay.agency_id else (stay.owner_id, None)
    else:
        account, agency = resolve_scope(request.user, agency_id)
    return Response(summary(account, agency, stay_id=stay_id))
