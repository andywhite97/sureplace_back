from django.urls import reverse
from django.core import mail
from django.core.cache import cache
from django.core import signing
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .email_verification import SALT, make_email_verification_token
from .models import User
from notifications.models import EmailDelivery


class AuthenticationTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.payload = {
            "first_name": "Nomsa",
            "last_name": "Dlamini",
            "email": "nomsa@example.com",
            "phone_number": "+26876123456",
            "password": "StrongPass123!",
            "onboarding_intents": ["LOOKING_FOR_PROPERTY", "PROPERTY_OWNER"],
        }

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=False,
    )
    def test_registration(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:register"), self.payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email=self.payload["email"])
        self.assertTrue(user.check_password(self.payload["password"]))
        self.assertFalse(user.is_email_verified)
        self.assertEqual(user.onboarding_intents, self.payload["onboarding_intents"])
        self.assertTrue(response.data["email_verification_required"])
        self.assertEqual(response.data["user"]["email"], self.payload["email"])
        self.assertNotIn("password", response.data)

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=False,
    )
    def test_registration_sends_verification_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:register"), self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 0)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.recipient, self.payload["email"])
        self.assertEqual(delivery.subject, "Verify your SurePlace email")
        self.assertEqual(delivery.template_key, "auth.verify_email")

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
            known = self.client.post(
                reverse("accounts:password-reset"), {"email": self.payload["email"]}, format="json"
            )
        unknown = self.client.post(reverse("accounts:password-reset"), {"email": "missing@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailDelivery.objects.count(), 1)
        self.assertEqual(EmailDelivery.objects.get().template_key, "auth.password_reset")

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

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_verify_email_valid_token_marks_verified_and_sends_welcome_once(self):
        user = User.objects.create_user(**self.payload)
        token = make_email_verification_token(user)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("accounts:verify-email"), {"token": token}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(EmailDelivery.objects.filter(template_key="auth.welcome").count(), 1)

        with self.captureOnCommitCallbacks(execute=True):
            repeated = self.client.post(reverse("accounts:verify-email"), {"token": token}, format="json")
        self.assertEqual(repeated.status_code, status.HTTP_200_OK)
        self.assertEqual(EmailDelivery.objects.filter(template_key="auth.welcome").count(), 1)

    @override_settings(EMAIL_VERIFICATION_TTL_SECONDS=-1)
    def test_verify_email_rejects_expired_token(self):
        user = User.objects.create_user(**self.payload)
        response = self.client.post(
            reverse("accounts:verify-email"), {"token": make_email_verification_token(user)}, format="json"
        )
        self.assertEqual(response.status_code, 410)

    def test_verify_email_rejects_bad_purpose_and_email_change(self):
        user = User.objects.create_user(**self.payload)
        wrong = signing.dumps({"purpose": "password_reset", "user_id": str(user.pk), "email": user.email}, salt=SALT)
        self.assertEqual(
            self.client.post(reverse("accounts:verify-email"), {"token": wrong}, format="json").status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        token = make_email_verification_token(user)
        user.email = "changed@example.com"
        user.save(update_fields=["email"])
        self.assertEqual(
            self.client.post(reverse("accounts:verify-email"), {"token": token}, format="json").status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_resend_verification_is_generic_and_only_sends_for_unverified(self):
        unknown = self.client.post(
            reverse("accounts:resend-verification"), {"email": "missing@example.com"}, format="json"
        )
        user = User.objects.create_user(**self.payload)
        known = self.client.post(reverse("accounts:resend-verification"), {"email": user.email}, format="json")
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(EmailDelivery.objects.filter(template_key="auth.verify_email").count(), 1)
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        self.client.post(reverse("accounts:resend-verification"), {"email": user.email}, format="json")
        self.assertEqual(EmailDelivery.objects.filter(template_key="auth.verify_email").count(), 1)

    def test_email_change_resets_verification_and_blocks_sensitive_write(self):
        user = User.objects.create_user(**self.payload, is_email_verified=True)
        self.client.force_authenticate(user)
        response = self.client.patch(reverse("accounts:me"), {"email": "new@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)
        self.assertIsNone(user.email_verified_at)

        blocked = self.client.post(reverse("property-list"), {}, format="json")
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.data["code"], "email_not_verified")

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
