from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import PropertyPlan, PropertyAddOnPackage
from .entitlements import resolve_scope, summary
from .models import PropertyListing
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
import uuid


@api_view(["GET"])
@permission_classes([AllowAny])
def property_pricing(request):
    plans = list(
        PropertyPlan.objects.filter(is_active=True).values(
            "code", "display_name", "price", "billing_interval", "active_listing_limit", "applicable_account_types"
        )
    )
    addons = list(
        PropertyAddOnPackage.objects.filter(is_active=True).values(
            "code", "display_name", "price", "quantity", "duration_days", "purchase_validity_days"
        )
    )
    for item in plans + addons:
        item["price"] = str(item["price"])
    return Response(
        {
            "currency": "SZL",
            "currency_symbol": "E",
            "checkout_available": False,
            "plans": plans,
            "addons": addons,
            "property_sales_commission_percent": 0,
            "features": [
                "Listing creation and editing",
                "Property photos",
                "Verification workflows",
                "Enquiry messaging",
                "Viewing requests",
                "Availability management",
                "Normal search visibility",
            ],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def property_entitlements(request):
    account, agency = resolve_scope(request.user, request.query_params.get("agency"))
    property_id = request.query_params.get("property")
    if property_id:
        try:
            property_id = uuid.UUID(property_id)
        except ValueError:
            raise ValidationError({"property": "A valid property UUID is required."})
        scope = {"agency_id": agency} if agency else {"owner_id": account, "agency_id": None}
        get_object_or_404(PropertyListing, pk=property_id, **scope)
    return Response(summary(account, agency, property_id=property_id))
