from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from core.views import config, health, ready, reference

urlpatterns = [
    path("health/", health, name="health"),
    path("health/ready/", ready, name="ready"),
    path("reference/", reference, name="reference"),
    path("config/", config, name="config"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="v1:schema"), name="redoc"),
    path("auth/", include("accounts.urls")),
    path("properties/", include("properties.urls")),
    path("", include("agencies.urls")),
    path("", include("stays.urls")),
    path("favourites/", include("favourites.urls")),
    path("", include("alerts.urls")),
    path("", include("messaging.urls")),
    path("", include("bookings.urls")),
    path("", include("notifications.urls")),
    path("", include("verification.urls")),
    path("", include("moderation.urls")),
]
