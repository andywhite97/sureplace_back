from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AgencyInvitationAcceptView,
    AgencyInvitationDeclineView,
    ManagementDashboardView,
    AgencyViewSet,
    PublicAgentViewSet,
    PublicAgencyDetailView,
)

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")
router.register("agents", PublicAgentViewSet, basename="agent")

urlpatterns = [
    path("management-dashboard/", ManagementDashboardView.as_view(), name="management-dashboard"),
    path("public-agencies/<slug:slug>/", PublicAgencyDetailView.as_view(), name="public-agency-detail"),
    *router.urls,
    path("agency-invitations/accept/", AgencyInvitationAcceptView.as_view(), name="agency-invitation-accept"),
    path("agency-invitations/decline/", AgencyInvitationDeclineView.as_view(), name="agency-invitation-decline"),
]
