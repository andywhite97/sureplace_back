from django.urls import reverse
from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User
from notifications.models import EmailDelivery


class AuthenticationTests(APITestCase):
    def setUp(self):
        self.payload = {
            "first_name": "Nomsa",
            "last_name": "Dlamini",
            "email": "nomsa@example.com",
            "phone_number": "+26876123456",
            "password": "StrongPass123!",
            "onboarding_intents": ["LOOKING_FOR_PROPERTY", "PROPERTY_OWNER"],
        }

    def test_registration(self):
        response = self.client.post(reverse("accounts:register"), self.payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.payload["email"])
        self.assertTrue(user.check_password(self.payload["password"]))
        self.assertEqual(user.onboarding_intents, self.payload["onboarding_intents"])
        self.assertNotIn("password", response.data)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user(**self.payload)
        duplicate = {**self.payload, "email": "NOMSA@example.com"}
        response = self.client.post(reverse("accounts:register"), duplicate, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_token_pair(self):
        User.objects.create_user(**self.payload)
        response = self.client.post(
            reverse("accounts:login"),
            {"email": self.payload["email"], "password": self.payload["password"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_change_password_requires_current_password(self):
        user = User.objects.create_user(**self.payload)
        self.client.force_authenticate(user)
        response = self.client.post(
            reverse("accounts:change-password"),
            {"current_password": "wrong", "new_password": "AnotherStrong123!", "confirm_password": "AnotherStrong123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("accounts:change-password"),
            {
                "current_password": self.payload["password"],
                "new_password": "AnotherStrong123!",
                "confirm_password": "AnotherStrong123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("AnotherStrong123!"))

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_password_reset_does_not_enumerate_accounts(self):
        User.objects.create_user(**self.payload)
        with self.captureOnCommitCallbacks(execute=True):
            known = self.client.post(reverse("accounts:password-reset"), {"email": self.payload["email"]}, format="json")
        unknown = self.client.post(reverse("accounts:password-reset"), {"email": "missing@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailDelivery.objects.count(), 1)
        self.assertEqual(EmailDelivery.objects.get().template_key, "password_reset")

    def test_logout_blacklists_refresh_token(self):
        user = User.objects.create_user(**self.payload)
        login = self.client.post(
            reverse("accounts:login"), {"email": user.email, "password": self.payload["password"]}, format="json"
        )
        self.client.force_authenticate(user)
        self.assertEqual(
            self.client.post(reverse("accounts:logout"), {"refresh": login.data["refresh"]}, format="json").status_code,
            204,
        )
        self.assertEqual(
            self.client.post(
                reverse("accounts:token-refresh"), {"refresh": login.data["refresh"]}, format="json"
            ).status_code,
            401,
        )

    def test_me_requires_authentication_and_returns_current_user(self):
        anonymous = self.client.get(reverse("accounts:me"))
        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
        user = User.objects.create_user(**self.payload)
        self.client.force_authenticate(user)
        response = self.client.get(reverse("accounts:me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], user.email)

    def test_refresh_issues_new_access_token(self):
        User.objects.create_user(**self.payload)
        login = self.client.post(
            reverse("accounts:login"),
            {"email": self.payload["email"], "password": self.payload["password"]},
            format="json",
        )
        response = self.client.post(
            reverse("accounts:token-refresh"), {"refresh": login.data["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
