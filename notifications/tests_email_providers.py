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
    sanitize_bird_tag_value,
)
from .models import EmailDelivery
from .services import enqueue_transactional_email, send_transactional_email
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

    def test_bird_tag_values_are_sanitized_without_changing_internal_values(self):
        self.assertEqual(sanitize_bird_tag_value("auth.welcome"), "auth_welcome")
        self.assertEqual(sanitize_bird_tag_value("tag with spaces"), "tag_with_spaces")
        self.assertEqual(sanitize_bird_tag_value("alerts/path/value"), "alerts_path_value")
        self.assertEqual(sanitize_bird_tag_value("already-valid_123"), "already-valid_123")
        self.assertEqual(sanitize_bird_tag_value("  ...///  "), "tag")
        self.assertEqual(sanitize_bird_tag_value("___"), "tag")

    @override_settings(
        EMAIL_PROVIDER="bird",
        BIRD_API_KEY="bk_eu1_test",
        DEFAULT_FROM_EMAIL="SurePlace <noreply@sureplace.co.sz>",
    )
    def test_bird_payload_sanitizes_generated_tag_values(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        message = build_email_message(
            "user@example.test",
            "Welcome",
            "Text",
            tags={
                "category": "auth.welcome",
                "spaces": "tag with spaces",
                "slashes": "alerts/path/value",
                "valid": "already-valid_123",
                "empty": "...///",
            },
        )
        with patch("notifications.email_providers.urlopen", fake_urlopen):
            result = get_email_provider().send(message)

        self.assertEqual(result.status, "accepted")
        self.assertEqual(
            [tag["value"] for tag in captured["payload"]["tags"]],
            ["auth_welcome", "tag_with_spaces", "alerts_path_value", "already-valid_123", "tag"],
        )

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="", BIRD_API_BASE_URL="")
    def test_bird_missing_configuration_fails_clearly(self):
        with self.assertRaises(ConfigurationEmailProviderError):
            get_email_provider()

    @override_settings(
        EMAIL_PROVIDER="bird",
        BIRD_API_KEY="bk_eu1_test",
        DEFAULT_FROM_EMAIL="SurePlace <not-an-email>",
    )
    def test_bird_rejects_invalid_sender_before_network_call(self):
        message = build_email_message("user@example.test", "Subject", "Text")
        with patch("notifications.email_providers.urlopen") as send:
            with self.assertRaisesRegex(PermanentEmailProviderError, "Invalid email address"):
                BirdEmailProvider().send(message)
        send.assert_not_called()

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

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_eu1_test")
    def test_bird_validation_error_preserves_one_safe_detail_and_request_id(self):
        response = self._http_error(
            422,
            {
                "error": {
                    "code": "E01001",
                    "message": "Request has 1 validation error.",
                    "request_id": "req_test_123",
                    "details": [{"param": "from.email", "message": "must be a valid email address"}],
                }
            },
        )
        with patch("notifications.email_providers.urlopen", side_effect=response):
            with self.assertRaises(PermanentEmailProviderError) as caught:
                BirdEmailProvider().send(build_email_message("user@example.test", "Subject", "Text"))

        self.assertEqual(caught.exception.code, "E01001")
        self.assertEqual(caught.exception.request_id, "req_test_123")
        self.assertEqual(
            str(caught.exception),
            "Request has 1 validation error. from.email: must be a valid email address",
        )

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_eu1_test")
    def test_bird_validation_error_preserves_multiple_safe_details(self):
        response = self._http_error(
            422,
            {
                "error": {
                    "code": "E01001",
                    "message": "Request has 2 validation errors.",
                    "details": [
                        {"param": "from.email", "message": "must be a valid email address"},
                        {"param": "to[0].email", "message": "must be a valid email address"},
                    ],
                }
            },
        )
        with patch("notifications.email_providers.urlopen", side_effect=response):
            with self.assertRaises(PermanentEmailProviderError) as caught:
                BirdEmailProvider().send(build_email_message("user@example.test", "Subject", "Text"))

        self.assertIn("from.email: must be a valid email address", str(caught.exception))
        self.assertIn("to[0].email: must be a valid email address", str(caught.exception))

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_eu1_test")
    def test_bird_validation_error_handles_missing_details(self):
        response = self._http_error(
            422,
            {"error": {"code": "E01001", "message": "Request has 1 validation error."}},
        )
        with patch("notifications.email_providers.urlopen", side_effect=response):
            with self.assertRaises(PermanentEmailProviderError) as caught:
                BirdEmailProvider().send(build_email_message("user@example.test", "Subject", "Text"))

        self.assertEqual(str(caught.exception), "Request has 1 validation error.")

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_eu1_test")
    def test_bird_validation_error_handles_malformed_response_without_secrets(self):
        secret = "reset-token-and-api-key"
        response = self._http_error(422, raw_body=f"not-json {secret}".encode())
        with patch("notifications.email_providers.urlopen", side_effect=response):
            with self.assertRaises(PermanentEmailProviderError) as caught:
                BirdEmailProvider().send(build_email_message("user@example.test", "Subject", "Text"))

        self.assertEqual(str(caught.exception), "Bird email request was rejected.")
        self.assertNotIn(secret, str(caught.exception))

    def _http_error(self, status_code, body=None, raw_body=None):
        if raw_body is None:
            raw_body = json.dumps(body or {"error": {"code": "validation_error", "message": "Invalid sender"}}).encode()
        return HTTPError(
            "https://us1.platform.bird.com/v1/email/messages",
            status_code,
            "error",
            {},
            BytesIO(raw_body),
        )


class EmailDeliveryTests(TestCase):

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_DELIVERY_MODE="async",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_enqueue_transactional_email_async_mode_queues_celery_task(self):
        with patch("notifications.tasks.send_email_delivery_task.apply_async") as apply_async:
            delivery = enqueue_transactional_email(
                "owner@sureplace.co.sz",
                "Booking requested",
                "You have a new booking request.",
                "/account/bookings",
                template_key="booking.confirmed",
                tags={"category": "booking.confirmed"},
            )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
        self.assertEqual(delivery.attempts, 0)
        self.assertEqual(len(mail.outbox), 0)
        apply_async.assert_called_once()
        self.assertFalse(apply_async.call_args.kwargs["retry"])

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_DELIVERY_MODE="sync",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    )
    def test_enqueue_transactional_email_sync_mode_sends_through_provider(self):
        with patch("notifications.tasks.send_email_delivery_task.apply_async") as apply_async:
            delivery = enqueue_transactional_email(
                "owner@sureplace.co.sz",
                "Booking requested",
                "You have a new booking request.",
                "/account/bookings",
                template_key="booking.confirmed",
                tags={"category": "booking.confirmed"},
            )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.ACCEPTED)
        self.assertEqual(delivery.provider, "django")
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.accepted_at)
        self.assertEqual(mail.outbox[0].to, ["owner@sureplace.co.sz"])
        apply_async.assert_not_called()

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_delivery_record_captures_provider_message_id_as_accepted(self):
        with patch("notifications.email_providers.urlopen", return_value=_Response()):
            result = send_transactional_email(
                "owner@sureplace.co.sz",
                "Booking requested",
                "You have a new booking request.",
                "/account/bookings",
                template_key="booking.confirmed",
                tags={"category": "booking.confirmed"},
            )

        delivery = EmailDelivery.objects.get()
        self.assertEqual(result.provider, "bird")
        self.assertEqual(delivery.provider, "bird")
        self.assertEqual(delivery.template_key, "booking.confirmed")
        self.assertEqual(delivery.provider_message_id, "em_test_123")
        self.assertEqual(delivery.status, EmailDelivery.Status.ACCEPTED)
        self.assertIsNotNone(delivery.accepted_at)
        self.assertIsNone(delivery.delivered_at)

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_celery_task_retries_transient_provider_failures(self):
        delivery = EmailDelivery.objects.create(recipient="user@sureplace.co.sz", subject="Subject", provider="bird")
        error = RetryableEmailProviderError("retry", status_code=429, code="rate_limited")
        with patch("notifications.tasks.send_email_delivery", side_effect=error):
            with self.assertRaises((Retry, RetryableEmailProviderError)):
                send_email_delivery_task(str(delivery.id), delivery.recipient, delivery.subject, "Text", "")

    @override_settings(EMAIL_PROVIDER="bird", BIRD_API_KEY="bk_us1_test", BIRD_API_BASE_URL="")
    def test_celery_task_does_not_retry_permanent_provider_failures(self):
        delivery = EmailDelivery.objects.create(recipient="user@sureplace.co.sz", subject="Subject", provider="bird")
        error = PermanentEmailProviderError("invalid sender", status_code=422, code="validation_error")
        with patch("notifications.tasks.send_email_delivery", side_effect=error):
            result = send_email_delivery_task(str(delivery.id), delivery.recipient, delivery.subject, "Text", "")
        self.assertEqual(result["status"], "failed")
