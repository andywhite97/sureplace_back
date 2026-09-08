import uuid

from django.conf import settings
from django.db.models import Exists, OuterRef, Q, Value, BooleanField
from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .filters import PropertyFilter
from .models import AvailabilityStatus, ListingStatus, PropertyListing
from .permissions import PropertyPermission
from .serializers import PropertyDetailSerializer, PropertyListSerializer, PropertyWriteSerializer
from .services import confirm_availability, pause_listing, submit_listing


class PropertyViewSet(viewsets.ModelViewSet):
    permission_classes = [PropertyPermission]
    filterset_class = PropertyFilter
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "description", "town", "suburb", "region"]
    lookup_field = "slug"
    lookup_value_regex = "[^/]+"

    def get_queryset(self):
        queryset = PropertyListing.objects.select_related("owner", "agency", "agent", "agent__user").prefetch_related(
            "amenities", "images"
        )
        if self.request.user.is_authenticated:
            from favourites.models import Favourite

            queryset = queryset.annotate(
                _is_favourited=Exists(Favourite.objects.filter(user=self.request.user, property_id=OuterRef("pk")))
            )
        else:
            queryset = queryset.annotate(_is_favourited=Value(False, output_field=BooleanField()))
        if self.action in {"list", "featured"}:
            queryset = queryset.filter(status=ListingStatus.PUBLISHED)

        params = self.request.query_params
        bounds = [params.get(name) for name in ("north", "south", "east", "west")]
        if any(value is not None for value in bounds):
            if not all(value is not None for value in bounds):
                raise ValidationError("north, south, east, and west must be supplied together.")
            try:
                north, south, east, west = map(float, bounds)
            except ValueError as exc:
                raise ValidationError("Map bounds must be valid numbers.") from exc
            if south > north or west > east:
                raise ValidationError("Map bounds are invalid.")
            if settings.USE_SQLITE:
                matching_ids = [
                    item.id
                    for item in queryset
                    if item.location and south <= item.latitude <= north and west <= item.longitude <= east
                ]
                queryset = queryset.filter(id__in=matching_ids)
            else:
                from django.contrib.gis.geos import Polygon

                queryset = queryset.filter(location__within=Polygon.from_bbox((west, south, east, north)))

        ordering = params.get("ordering", "newest")
        ordering_map = {
            "newest": "-created_at",
            "oldest": "created_at",
            "price_asc": "price",
            "price_desc": "-price",
        }
        if ordering not in ordering_map:
            raise ValidationError({"ordering": f"Choose one of: {', '.join(ordering_map)}."})
        return queryset.order_by(ordering_map[ordering]).distinct()

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        return PropertyFilter(self.request.query_params, queryset=queryset).qs

    def get_object(self):
        value = self.kwargs[self.lookup_field]
        query = Q(slug=value)
        try:
            query |= Q(id=uuid.UUID(value))
        except ValueError:
            pass
        obj = get_object_or_404(self.get_queryset(), query)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_serializer_class(self):
        if self.action == "list" or self.action == "featured":
            return PropertyListSerializer
        if self.action in {"create", "update", "partial_update"}:
            return PropertyWriteSerializer
        return PropertyDetailSerializer

    @action(detail=False, methods=["get"])
    def featured(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(featured=True, availability_status=AvailabilityStatus.AVAILABLE)
        )
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @action(detail=False, methods=["get"])
    def mine(self, request):
        if not request.user.is_authenticated:
            from rest_framework.exceptions import NotAuthenticated

            raise NotAuthenticated()
        queryset = self.filter_queryset(
            self.get_queryset().filter(
                Q(owner=request.user)
                | Q(agent__user=request.user, agent__is_active=True)
                | Q(agency__agents__user=request.user, agency__agents__is_active=True)
            )
        )
        page = self.paginate_queryset(queryset)
        serializer = PropertyDetailSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)

    def _transition(self, service):
        listing = self.get_object()
        try:
            service(listing)
        except Exception as exc:
            if hasattr(exc, "message_dict"):
                raise ValidationError(exc.message_dict) from exc
            if hasattr(exc, "messages"):
                raise ValidationError(exc.messages) from exc
            raise
        return Response(PropertyDetailSerializer(listing, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, **kwargs):
        return self._transition(submit_listing)

    @action(detail=True, methods=["post"])
    def pause(self, request, **kwargs):
        return self._transition(pause_listing)

    @action(detail=True, methods=["post"], url_path="confirm-availability")
    def confirm_availability_action(self, request, **kwargs):
        return self._transition(confirm_availability)

    @action(detail=True, methods=["post", "patch", "delete"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def images(self, request, **kwargs):
        listing = self.get_object()
        if not can_manage_property(request.user, listing):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied()
        if request.method == "POST":
            serializer = PropertyImageSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            image = serializer.save(property=listing)
            return Response(PropertyImageSerializer(image).data, status=201)
        image = get_object_or_404(listing.images, pk=request.data.get("id") or request.query_params.get("id"))
        if request.method == "DELETE":
            image.image.delete(save=False)
            image.delete()
            return Response(status=204)
        serializer = PropertyImageSerializer(image, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
