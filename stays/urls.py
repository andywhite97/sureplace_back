from rest_framework.routers import DefaultRouter
from .views import RoomViewSet, StayViewSet

router = DefaultRouter()
router.register("stays", StayViewSet, basename="stay")
router.register("rooms", RoomViewSet, basename="room")
urlpatterns = router.urls
