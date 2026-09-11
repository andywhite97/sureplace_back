from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AgencyInvitationAcceptView, AgencyInvitationDeclineView, AgencyViewSet

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")

urlpatterns = [
    *router.urls,
    path("agency-invitations/accept/", AgencyInvitationAcceptView.as_view(), name="agency-invitation-accept"),
    path("agency-invitations/decline/", AgencyInvitationDeclineView.as_view(), name="agency-invitation-decline"),
]
