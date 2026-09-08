import json
import socket
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from celery.exceptions import Retry
from django.core import mail
from django.test import TestCase, override_settings

from .email_providers import (
    BirdEmailProvider,
    ConfigurationEmailProviderError,
    PermanentEmailProviderError,
    RetryableEmailProviderError,
    build_email_message,
    get_email_provider,
)
from .models import EmailDelivery
from .services import send_transactional_email
from .tasks import send_email_delivery_task


class _Response:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"id":"em_test_123","status":"accepted"}'


class BirdEmailProviderTests(TestCase):
    @override_settings(EMAIL_PROVIDER="django", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_development_django_provider_uses_django_backend(self):
        provider = get_email_provider()
        message = build_email_message("user@example.test", "Subject", "Plain text", "<p>Plain text</p>")
        result = provider.send(message)

        self.assertEqual(result.provider, "django")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(mail.outbox[0].subject, "Subject")

    @override_settings(
        EMAIL_PROVIDER="bird",
        BIRD_API_KEY="bk_eu1_test",
        BIRD_API_BASE_URL="",
        DEFAULT_FROM_EMAIL="SurePlace <noreply@sureplace.co.sz>",
        DEFAULT_FROM_NAME="SurePlace",
        DEFAULT_REPLY_TO_EMAIL="Support <support@sureplace.co.sz>",
        BIRD_TRACK_OPENS=False,
        BIRD_TRACK_CLICKS=False,
    )
    def test_bird_payload_headers_region_and_message_id_capture(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        message = build_email_message(
            "Nomsa Dlamini <nomsa@sureplace.co.sz>",
            "Reset your SurePlace password",
            "Text body",
            "<p>HTML body</p>",
            cc=["cc@sureplace.co.sz"],
            bcc=["bcc@sureplace.co.sz"],
            template_key="password_reset",
            tags={"category": "password_reset"},
            metadata={"notification_id": "not_123"},
            idempotency_key="delivery-123",
        )
        with patch("notifications.email_providers.urlopen", fake_urlopen):
            result = BirdEmailProvider().send(message)

        self.assertEqual(captured["url"], "https://eu1.platform.bird.com/v1/email/messages")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer bk_eu1_test")
        self.assertEqual(captured["headers"]["Content-type"], "application/json")
        self.assertEqual(captured["headers"]["Idempotency-key"], "delivery-123")
        self.assertEqual(captured["payload"]["category"], "transactional")
        self.assertEqual(captured["payload"]["from"], {"email": "noreply@sureplace.co.sz", "name": "SurePlace"})
        self.assertEqual(captured["payload"]["to"], [{"email": "nomsa@sureplace.co.sz", "name": "Nomsa Dlamini"}])
        self.assertEqual(captured["payload"]["subject"], "Reset your SurePlace password")
        self.assertEqual(captured["payload"]["html"], "<p>HTML body</p>")
        self.assertEqual(captured["payload"]["text"], "Text body")
        self.assertEqual(captured["payload"]["reply_to"], [{"email": "support@sureplace.co.sz", "name": "Support"}])
        self.assertFalse(captured["payload"]["track_opens"])
        self.assertFalse(captured["payload"]["track_clicks"])
        self.assertEqual(captured["payload"]["tags"], [{"name": "category", "value": "password_reset"}])
        self.assertEqual(result.provider_message_id, "em_test_123")
        self.assertEqual(result.status, "accepted")

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="", BIRD_API_BASE_URL="")
    def test_bird_missing_configuration_fails_clearly(self):
        with self.assertRaises(ConfigurationEmailProviderError):
            get_email_provider()

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="http://example.com")
    def test_bird_rejects_insecure_base_url_override(self):
        with self.assertRaises(ConfigurationEmailProviderError):
            BirdEmailProvider()

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_bird_timeout_is_retryable(self):
        message = build_email_message("user@sureplace.co.sz", "Subject", "Text")
        with patch("notifications.email_providers.urlopen", side_effect=socket.timeout):
            with self.assertRaises(RetryableEmailProviderError):
                BirdEmailProvider().send(message)

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_bird_429_and_500_are_retryable_but_422_is_permanent(self):
        message = build_email_message("user@sureplace.co.sz", "Subject", "Text")
        for status_code in (429, 500):
            with patch("notifications.email_providers.urlopen", side_effect=self._http_error(status_code)):
                with self.assertRaises(RetryableEmailProviderError):
                    BirdEmailProvider().send(message)
        with patch("notifications.email_providers.urlopen", side_effect=self._http_error(422)):
            with self.assertRaises(PermanentEmailProviderError):
                BirdEmailProvider().send(message)

    def _http_error(self, status_code):
        return HTTPError(
            "https://us1.platform.bird.com/v1/email/messages",
            status_code,
            "error",
            {},
            BytesIO(b'{"error":{"code":"validation_error","message":"Invalid sender"}}'),
        )


class EmailDeliveryTests(TestCase):
    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_delivery_record_captures_provider_message_id_as_accepted(self):
        with patch("notifications.email_providers.urlopen", return_value=_Response()):
            result = send_transactional_email(
                "owner@sureplace.co.sz",
                "Booking requested",
                "You have a new booking request.",
                "/account/bookings",
                template_key="booking",
                tags={"category": "booking"},
            )

        delivery = EmailDelivery.objects.get()
        self.assertEqual(result.provider, "bird")
        self.assertEqual(delivery.provider, "bird")
        self.assertEqual(delivery.provider_message_id, "em_test_123")
        self.assertEqual(delivery.status, EmailDelivery.Status.ACCEPTED)
        self.assertIsNotNone(delivery.accepted_at)
        self.assertIsNone(delivery.delivered_at)

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_celery_task_retries_transient_provider_failures(self):
        delivery = EmailDelivery.objects.create(recipient="user@sureplace.co.sz", subject="Subject", provider="bird")
        error = RetryableEmailProviderError("retry", status_code=429, code="rate_limited")
        with patch("notifications.tasks.send_email_delivery", side_effect=error):
            with self.assertRaises(Retry):
                send_email_delivery_task(str(delivery.id), delivery.recipient, delivery.subject, "Text", "")

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_celery_task_does_not_retry_permanent_provider_failures(self):
        delivery = EmailDelivery.objects.create(recipient="user@sureplace.co.sz", subject="Subject", provider="bird")
        error = PermanentEmailProviderError("invalid sender", status_code=422, code="validation_error")
        with patch("notifications.tasks.send_email_delivery", side_effect=error):
            result = send_email_delivery_task(str(delivery.id), delivery.recipient, delivery.subject, "Text", "")
        self.assertEqual(result["status"], "failed")
