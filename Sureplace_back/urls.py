from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(("Sureplace_back.api_urls", "api_v1"), namespace="v1")),
    path("api/health/", __import__("core.views", fromlist=["health"]).health, name="health"),
    path("api/auth/", include("accounts.urls")),
    path("api/properties/", include("properties.urls")),
    path("api/", include("stays.urls")),
    path("api/favourites/", include("favourites.urls")),
    path("api/", include("alerts.urls")),
    path("api/", include("messaging.urls")),
    path("api/", include("bookings.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("verification.urls")),
    path("api/", include("moderation.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
