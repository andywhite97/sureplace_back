from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import BookingViewSet, ViewingViewSet, create_stay_booking, create_viewing

router = DefaultRouter()
router.register("viewing-requests", ViewingViewSet, basename="viewing-request")
router.register("bookings", BookingViewSet, basename="booking")
urlpatterns = router.urls + [
    path("properties/<uuid:property_id>/viewing-requests/", create_viewing),
    path("stays/<uuid:stay_id>/bookings/", create_stay_booking),
]
