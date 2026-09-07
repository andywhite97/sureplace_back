from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import SavedSearchViewSet, seeker_summary

router = DefaultRouter()
router.register("saved-searches", SavedSearchViewSet, basename="saved-search")
urlpatterns = router.urls + [path("dashboard/seeker-summary/", seeker_summary)]
