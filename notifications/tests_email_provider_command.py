from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from .email_providers import (
    ConfigurationEmailProviderError,
    EmailProviderResult,
    PermanentEmailProviderError,
    RetryableEmailProviderError,
)
from .email_templates import render_email, sample_context


class _Provider:
    provider = "bird"


@override_settings(
    EMAIL_PROVIDER="bird",
    BIRD_API_KEY="bk_us1_test_key",
    BIRD_API_BASE_URL="",
    DEFAULT_FROM_EMAIL="SurePlace <noreply@sureplace.co.sz>",
    DEFAULT_FROM_NAME="SurePlace",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEBUG=False,
)
class EmailProviderDiagnosticCommandTests(SimpleTestCase):
    def call(self, *args):
        out = StringIO()
        call_command("test_email_provider", *args, stdout=out)
        return out.getvalue()

    def test_valid_recipient_sends_synchronously_and_prints_accepted_result(self):
        with (
            patch("notifications.management.commands.test_email_provider.get_email_provider", return_value=_Provider()),
            patch(
                "notifications.management.commands.test_email_provider.send_transactional_email",
                return_value=EmailProviderResult("bird", "em_test_123", "accepted"),
            ) as send,
        ):
            output = self.call("admin@example.com")

        self.assertIn("Email provider diagnostic successful.", output)
        self.assertIn("Provider: bird", output)
        self.assertIn("Status: accepted", output)
        self.assertIn("Message ID: em_test_123", output)
        self.assertIn("Bird accepted the message for delivery.", output)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], "admin@example.com")
        self.assertEqual(send.call_args.args[1], "SurePlace email delivery test")
        self.assertIn("configured correctly", send.call_args.args[2])
        self.assertEqual(send.call_args.kwargs["template_key"], "system.email_diagnostic")

    def test_invalid_recipient_fails_before_provider_resolution(self):
        with patch("notifications.management.commands.test_email_provider.get_email_provider") as provider:
            with self.assertRaisesMessage(CommandError, "Invalid recipient email address."):
                self.call("not-an-email")

        provider.assert_not_called()

    def test_diagnostic_template_renders_html_and_text(self):
        rendered = render_email("system.email_diagnostic", sample_context("system.email_diagnostic"))

        self.assertEqual(rendered.subject, "SurePlace email delivery test")
        self.assertIn("configured correctly", rendered.html)
        self.assertIn("No action is required.", rendered.text)

    def test_dry_run_resolves_provider_and_skips_send_and_queue(self):
        with (
            patch("notifications.management.commands.test_email_provider.get_email_provider", return_value=_Provider()),
            patch("notifications.management.commands.test_email_provider.send_transactional_email") as send,
            patch("notifications.management.commands.test_email_provider.enqueue_transactional_email") as enqueue,
        ):
            output = self.call("admin@example.com", "--dry-run")

        self.assertIn("Dry run successful.", output)
        self.assertIn("Template: system.email_diagnostic", output)
        self.assertIn("Network call: skipped", output)
        send.assert_not_called()
        enqueue.assert_not_called()

    def test_via_celery_queues_instead_of_direct_provider_send(self):
        delivery = SimpleNamespace(id="delivery-123")
        with (
            patch("notifications.management.commands.test_email_provider.get_email_provider", return_value=_Provider()),
            patch(
                "notifications.management.commands.test_email_provider.enqueue_transactional_email",
                return_value=delivery,
            ) as enqueue,
            patch("notifications.management.commands.test_email_provider.send_transactional_email") as send,
        ):
            output = self.call("admin@example.com", "--via-celery")

        self.assertIn("Diagnostic email queued.", output)
        self.assertIn("Provider: bird", output)
        self.assertIn("Delivery ID: delivery-123", output)
        enqueue.assert_called_once()
        send.assert_not_called()

    def test_missing_configuration_is_reported_safely(self):
        with patch(
            "notifications.management.commands.test_email_provider.get_email_provider",
            side_effect=ConfigurationEmailProviderError("BIRD_API_KEY is required when EMAIL_PROVIDER=bird."),
        ):
            with self.assertRaisesMessage(CommandError, "BIRD_API_KEY is required"):
                self.call("admin@example.com")

    def test_provider_error_mapping_is_safe(self):
        cases = [
            (
                PermanentEmailProviderError("secret key bk_us1_secret", status_code=401),
                "Bird authentication failed. Check BIRD_API_KEY.",
            ),
            (
                PermanentEmailProviderError("forbidden", status_code=403),
                "Bird rejected this API key or permission scope.",
            ),
            (
                PermanentEmailProviderError("Invalid sender domain", status_code=422, code="validation_error"),
                "Check that DEFAULT_FROM_EMAIL belongs to a verified Bird sending domain.",
            ),
            (
                RetryableEmailProviderError("rate limited", status_code=429),
                "Bird rate limit reached. Try again later.",
            ),
            (
                RetryableEmailProviderError("server error", status_code=503),
                "Bird is temporarily unavailable.",
            ),
            (
                RetryableEmailProviderError("Bird email request failed transiently.", code="network_error"),
                "Bird request timed out.",
            ),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                with (
                    patch(
                        "notifications.management.commands.test_email_provider.get_email_provider",
                        return_value=_Provider(),
                    ),
                    patch(
                        "notifications.management.commands.test_email_provider.send_transactional_email",
                        side_effect=error,
                    ),
                ):
                    with self.assertRaisesMessage(CommandError, expected) as caught:
                        self.call("admin@example.com")

                self.assertNotIn("bk_us1_secret", str(caught.exception))

    @override_settings(EMAIL_PROVIDER="django", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_django_provider_reports_backend(self):
        provider = SimpleNamespace(provider="django")
        with (
            patch("notifications.management.commands.test_email_provider.get_email_provider", return_value=provider),
            patch(
                "notifications.management.commands.test_email_provider.send_transactional_email",
                return_value=EmailProviderResult("django", "", "accepted"),
            ),
        ):
            output = self.call("admin@example.com")

        self.assertIn("Provider: django", output)
        self.assertIn("Backend: django.core.mail.backends.locmem.EmailBackend", output)
        self.assertIn("Message ID: unavailable", output)

    @override_settings(DEBUG=True)
    def test_debug_bird_warning_does_not_expose_secret(self):
        with (
            patch("notifications.management.commands.test_email_provider.get_email_provider", return_value=_Provider()),
            patch(
                "notifications.management.commands.test_email_provider.send_transactional_email",
                return_value=EmailProviderResult("bird", "em_test_123", "accepted"),
            ),
        ):
            output = self.call("admin@example.com")

        self.assertIn("Warning: DEBUG is enabled and EMAIL_PROVIDER=bird will send externally.", output)
        self.assertNotIn("bk_us1_test_key", output)
