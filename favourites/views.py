from rest_framework import permissions, viewsets
from .models import Favourite
from .serializers import FavouriteSerializer


class FavouriteViewSet(viewsets.ModelViewSet):
    serializer_class = FavouriteSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = (
            Favourite.objects.filter(user=self.request.user)
            .select_related("property", "stay")
            .prefetch_related("property__images", "stay__images", "stay__room_types")
        )
        kind = self.request.query_params.get("type")
        return qs.filter(**{kind + "__isnull": False}) if kind in ("property", "stay") else qs
