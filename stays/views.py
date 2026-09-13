import uuid
from datetime import date, timedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import BooleanField, Count, Exists, Min, OuterRef, Prefetch, Q, Value
from django.shortcuts import get_object_or_404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from accounts.permissions import IsEmailVerified
from .models import *
from .serializers import *
from .services import can_manage, pause, room_availability, submit


class StayViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsEmailVerified]

    def get_queryset(self):
        action = getattr(self, "action", None)
        if action in ("list", "featured"):
            cover_images = Prefetch(
                "images",
                queryset=StayImage.objects.filter(is_cover=True).order_by("sort_order", "created_at"),
                to_attr="_cover_images",
            )
            qs = (
                Stay.objects.select_related("agency", "agent", "agent__user")
                .prefetch_related(cover_images)
                .annotate(
                    _minimum_nightly_price=Min(
                        "room_types__base_price",
                        filter=Q(room_types__is_active=True),
                    ),
                    _available_room_type_count=Count(
                        "room_types",
                        filter=Q(room_types__is_active=True, room_types__quantity__gt=0),
                        distinct=True,
                    ),
                )
            )
        else:
            qs = Stay.objects.select_related("agency", "agent", "agent__user").prefetch_related(
                "images",
                "amenities",
                "room_types__images",
            )
        if self.request.user.is_authenticated:
            from favourites.models import Favourite

            qs = qs.annotate(
                _is_favourited=Exists(Favourite.objects.filter(user=self.request.user, stay_id=OuterRef("pk")))
            )
        else:
            qs = qs.annotate(_is_favourited=Value(False, output_field=BooleanField()))
        if self.action in ("list", "featured"):
            qs = qs.filter(status=StayStatus.PUBLISHED)
        p = self.request.query_params
        for field in ("stay_type", "featured", "verification_status"):
            if p.get(field) is not None:
                qs = qs.filter(**{field: p[field]})
        for field in ("region", "town", "suburb"):
            if p.get(field):
                qs = qs.filter(**{field + "__iexact": p[field]})
        if p.get("search"):
            qs = qs.filter(
                Q(name__icontains=p["search"])
                | Q(description__icontains=p["search"])
                | Q(town__icontains=p["search"])
                | Q(suburb__icontains=p["search"])
            )
        if p.get("amenities"):
            qs = qs.filter(amenities__id=p["amenities"])
        if p.get("min_price"):
            qs = qs.filter(room_types__base_price__gte=p["min_price"])
        if p.get("max_price"):
            qs = qs.filter(room_types__base_price__lte=p["max_price"])
        bounds = [p.get(k) for k in ("north", "south", "east", "west")]
        if any(v is not None for v in bounds):
            if not all(v is not None for v in bounds):
                raise ValidationError("All four map bounds are required.")
            north, south, east, west = map(float, bounds)
            if settings.USE_SQLITE:
                ids = [s.id for s in qs if s.location and south <= s.latitude <= north and west <= s.longitude <= east]
                qs = qs.filter(id__in=ids)
            else:
                from django.contrib.gis.geos import Polygon

                qs = qs.filter(location__within=Polygon.from_bbox((west, south, east, north)))
        dates = [p.get("check_in"), p.get("check_out")]
        if any(dates):
            if not all(dates):
                raise ValidationError("check_in and check_out are required together.")
            try:
                ci, co = map(date.fromisoformat, dates)
                adults = int(p.get("adults", 1))
                children = int(p.get("children", 0))
                rooms = int(p.get("rooms", 1))
            except ValueError as e:
                raise ValidationError("Invalid availability search values.") from e
            ids = [
                s.id
                for s in qs
                if any(
                    room_availability(r, ci, co, adults, children, rooms)["available"]
                    for r in s.room_types.all()
                    if r.is_active
                )
            ]
            qs = qs.filter(id__in=ids)
        ordering = {
            "newest": "-created_at",
            "price_asc": "room_types__base_price",
            "price_desc": "-room_types__base_price",
            "name": "name",
        }.get(p.get("ordering", "newest"), "-created_at")
        return qs.order_by(ordering).distinct()

    def get_object(self):
        value = self.kwargs["pk"]
        query = Q(slug=value)
        try:
            query |= Q(id=uuid.UUID(value))
        except ValueError:
            pass
        obj = get_object_or_404(self.get_queryset(), query)
        if self.request.method not in permissions.SAFE_METHODS and not can_manage(self.request.user, obj):
            raise PermissionDenied()
        if (
            self.request.method in permissions.SAFE_METHODS
            and obj.status != StayStatus.PUBLISHED
            and not can_manage(self.request.user, obj)
        ):
            raise PermissionDenied()
        return obj

    def get_serializer_class(self):
        return (
            StayWriteSerializer
            if self.action in ("create", "update", "partial_update")
            else (StayListSerializer if self.action in ("list", "featured") else StayDetailSerializer)
        )

    @action(detail=False, methods=["get"])
    def featured(self, request):
        cache_key = "stays:featured:v2"
        if not request.user.is_authenticated:
            cached = cache.get(cache_key)
            if cached is not None:
                response = Response(cached)
                response["Cache-Control"] = f"public, max-age={settings.FEATURED_LISTINGS_CACHE_SECONDS}"
                return response
        qs = self.get_queryset().filter(featured=True, room_types__is_active=True)
        items = list(qs[:6])
        data = {
            "count": len(items),
            "next": None,
            "previous": None,
            "results": self.get_serializer(items, many=True).data,
        }
        if not request.user.is_authenticated:
            cache.set(cache_key, data, settings.FEATURED_LISTINGS_CACHE_SECONDS)
        response = Response(data)
        response["Cache-Control"] = (
            f"public, max-age={settings.FEATURED_LISTINGS_CACHE_SECONDS}"
            if not request.user.is_authenticated
            else "private, no-store"
        )
        return response

    @action(detail=False, methods=["get"])
    def mine(self, request):
        if not request.user.is_authenticated:
            raise NotAuthenticated()
        qs = self.filter_queryset(
            self.get_queryset().filter(
                Q(owner=request.user)
                | Q(agent__user=request.user, agent__is_active=True)
                | Q(agency__agents__user=request.user, agency__agents__is_active=True)
            )
        )
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(StayDetailSerializer(page, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        obj = self.get_object()
        submit(obj)
        return Response(StayDetailSerializer(obj, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        obj = self.get_object()
        pause(obj)
        return Response(StayDetailSerializer(obj, context={"request": request}).data)

    @action(detail=True, methods=["post", "patch", "delete"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def images(self, request, pk=None):
        stay = self.get_object()
        if not can_manage(request.user, stay):
            raise PermissionDenied()
        if request.method == "POST":
            s = ImageSerializer(data=request.data)
            s.is_valid(raise_exception=True)
            image = s.save(stay=stay)
            return Response(ImageSerializer(image).data, status=201)
        image = get_object_or_404(stay.images, pk=request.data.get("id") or request.query_params.get("id"))
        if request.method == "DELETE":
            image.image.delete(save=False)
            image.delete()
            return Response(status=204)
        s = ImageSerializer(image, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    @action(detail=True, methods=["get", "post"])
    def rooms(self, request, pk=None):
        stay = self.get_object()
        if request.method == "GET":
            return Response(
                RoomSerializer(
                    stay.room_types.all() if can_manage(request.user, stay) else stay.room_types.filter(is_active=True),
                    many=True,
                    context={"request": request},
                ).data
            )
        if not can_manage(request.user, stay):
            raise PermissionDenied()
        s = RoomWriteSerializer(data=request.data, context={"stay": stay})
        s.is_valid(raise_exception=True)
        room = s.save(stay=stay)
        return Response(RoomSerializer(room, context={"request": request}).data, status=201)

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        stay = self.get_object()
        try:
            check_in = date.fromisoformat(request.query_params["check_in"])
            check_out = date.fromisoformat(request.query_params["check_out"])
            adults = int(request.query_params.get("adults", 1))
            children = int(request.query_params.get("children", 0))
            rooms = int(request.query_params.get("rooms", 1))
        except (KeyError, ValueError) as e:
            raise ValidationError("Valid check_in and check_out are required.") from e
        results = [
            room_availability(r, check_in, check_out, adults, children, rooms)
            for r in stay.room_types.filter(is_active=True)
        ]
        return Response({"stay_id": str(stay.id), "room_types": [r for r in results if r["available"]]})


class RoomViewSet(viewsets.ModelViewSet):
    queryset = RoomType.objects.select_related("stay").prefetch_related("images")
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsEmailVerified]

    def get_serializer_class(self):
        return RoomWriteSerializer if self.action in ("update", "partial_update") else RoomSerializer

    def get_object(self):
        obj = super().get_object()
        if self.request.method not in permissions.SAFE_METHODS and not can_manage(self.request.user, obj.stay):
            raise PermissionDenied()
        return obj

    def get_serializer_context(self):
        return (
            {**super().get_serializer_context(), "stay": getattr(self.get_object(), "stay", None)}
            if self.action in ("update", "partial_update")
            else super().get_serializer_context()
        )

    @action(detail=True, methods=["post"], url_path="availability/bulk")
    def bulk(self, request, pk=None):
        room = self.get_object()
        try:
            start = date.fromisoformat(request.data["start_date"])
            end = date.fromisoformat(request.data["end_date"])
        except (KeyError, ValueError) as e:
            raise ValidationError("Valid start_date and end_date are required.") from e
        if end < start:
            raise ValidationError("end_date must not precede start_date.")
        defaults = {
            k: request.data[k]
            for k in ("available_units", "custom_price", "minimum_stay_override", "is_blocked")
            if k in request.data
        }
        count = 0
        day = start
        while day <= end:
            obj, _ = RoomAvailability.objects.update_or_create(room_type=room, date=day, defaults=defaults)
            obj.full_clean()
            obj.save()
            count += 1
            day += timedelta(days=1)
        return Response({"updated": count})

    @action(detail=True, methods=["post", "patch", "delete"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def images(self, request, pk=None):
        room = self.get_object()
        if not can_manage(request.user, room.stay):
            raise PermissionDenied()
        if request.method == "POST":
            s = RoomImageSerializer(data=request.data, context={"request": request})
            s.is_valid(raise_exception=True)
            image = s.save(room_type=room)
            return Response(RoomImageSerializer(image, context={"request": request}).data, status=201)
        image = get_object_or_404(room.images, pk=request.data.get("id") or request.query_params.get("id"))
        if request.method == "DELETE":
            image.image.delete(save=False)
            image.delete()
            return Response(status=204)
        s = RoomImageSerializer(image, data=request.data, partial=True, context={"request": request})
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    @action(detail=True, methods=["get"])
    def calendar(self, request, pk=None):
        from bookings.services import inventory, reserved_units

        room = self.get_object()
        try:
            start = date.fromisoformat(request.query_params["start"])
            end = date.fromisoformat(request.query_params["end"])
        except (KeyError, ValueError) as e:
            raise ValidationError("Valid start and end are required.") from e
        rows = {r.date: r for r in room.availability.filter(date__gte=start, date__lte=end)}
        data = []
        day = start
        while day <= end:
            row = rows.get(day)
            data.append(
                {
                    "date": str(day),
                    "base_inventory": room.quantity,
                    "manual_inventory": row.available_units if row else None,
                    "reserved_units": reserved_units(room, day),
                    "available_units": inventory(room, day),
                    "blocked": bool(row and row.is_blocked),
                    "effective_price": str(room.effective_price(day)),
                }
            )
            day += timedelta(days=1)
        return Response(data)
