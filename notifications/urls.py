from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet, PreferenceViewSet

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register("notification-preferences", PreferenceViewSet, basename="notification-preference")
urlpatterns = router.urls
