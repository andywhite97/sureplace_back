from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import RequestViewSet, ReviewViewSet, delete_document, download_document, types

router = DefaultRouter()
router.register("verification/requests", RequestViewSet, basename="verification-request")
router.register("moderation/verifications", ReviewViewSet, basename="verification-review")
urlpatterns = router.urls + [
    path("verification/types/", types),
    path("verification/documents/<uuid:document_id>/download/", download_document),
    path("verification/documents/<uuid:document_id>/", delete_document),
]
