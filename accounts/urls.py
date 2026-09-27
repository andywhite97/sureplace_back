from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordView,
    CapabilitySummaryView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetView,
    RegisterView,
    ResendVerificationView,
    StaffUserDirectoryView,
    StaffUserDetailView,
    StaffUserModerationActionView,
    StaffAccessView,
    StaffAccessRoleDetailView,
    StaffUserRolesView,
    VerifyEmailView,
)

app_name = "accounts"
urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("capabilities/", CapabilitySummaryView.as_view(), name="capabilities"),
    path("staff/users/", StaffUserDirectoryView.as_view(), name="staff-users"),
    path("staff/access/", StaffAccessView.as_view(), name="staff-access"),
    path("staff/access/roles/<int:pk>/", StaffAccessRoleDetailView.as_view(), name="staff-access-role-detail"),
    path("staff/users/<uuid:pk>/", StaffUserDetailView.as_view(), name="staff-user-detail"),
    path("staff/users/<uuid:pk>/roles/", StaffUserRolesView.as_view(), name="staff-user-roles"),
    path("staff/users/<uuid:pk>/<str:action>/", StaffUserModerationActionView.as_view(), name="staff-user-moderation"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("resend-verification/", ResendVerificationView.as_view(), name="resend-verification"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("password-reset/", PasswordResetView.as_view(), name="password-reset"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
