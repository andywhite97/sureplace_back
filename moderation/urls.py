from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import ReportCreateViewSet, ReportReviewViewSet, listing_action, summary

router = DefaultRouter()
router.register("reports/listings", ReportCreateViewSet, basename="listing-report")
router.register("moderation/reports", ReportReviewViewSet, basename="moderation-report")
urlpatterns = router.urls + [
    path("moderation/listings/<str:target_type>/<uuid:target_id>/<str:action_name>/", listing_action),
    path("moderation/summary/", summary),
]
