from django.test import SimpleTestCase, override_settings

from .email_templates import TEMPLATES, absolute_url, render_email, sample_context, template_for_notification


@override_settings(
    FRONTEND_BASE_URL="https://app.sureplace.test",
    EMAIL_LOGO_URL="",
    DEFAULT_REPLY_TO_EMAIL="support@sureplace.test",
)
class EmailTemplateRenderingTests(SimpleTestCase):
    def test_every_template_key_resolves_with_html_and_plain_text(self):
        for key in TEMPLATES:
            with self.subTest(key=key):
                rendered = render_email(key, sample_context(key))
                self.assertTrue(rendered.subject)
                self.assertIn("<!doctype html>", rendered.html)
                self.assertIn("SurePlace", rendered.html)
                self.assertIn("Property. Without the noise.", rendered.html)
                self.assertIn("https://app.sureplace.test", rendered.html)
                self.assertIn("SurePlace", rendered.text)
                self.assertNotIn("localhost", rendered.html)

    def test_base_template_renders_text_logo_fallback_and_preheader(self):
        rendered = render_email(
            "transactional",
            {
                "subject": "Test update",
                "headline": "Test update",
                "message": "Preview body",
                "preheader": "Hidden preview",
                "cta_url": "/account",
            },
        )

        self.assertIn("Hidden preview", rendered.html)
        self.assertIn('<span style="color:#0F9D83;">Sure</span>', rendered.html)
        self.assertIn("Property. Without the noise.", rendered.html)

    def test_cta_urls_are_absolute(self):
        self.assertEqual(absolute_url("/properties/demo"), "https://app.sureplace.test/properties/demo")
        rendered = render_email("auth.welcome", {"message": "Ready", "cta_url": "/properties"})
        self.assertIn('href="https://app.sureplace.test/properties"', rendered.html)
        self.assertIn("Explore Properties: https://app.sureplace.test/properties", rendered.text)

    def test_html_escaping_protects_user_generated_content(self):
        rendered = render_email(
            "messaging.new_message",
            {
                "message": "<script>alert(1)</script>",
                "message_preview": "<b>hello</b>",
                "cta_url": "/account/messages/1",
            },
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered.html)
        self.assertIn("&lt;b&gt;hello&lt;/b&gt;", rendered.html)
        self.assertNotIn("<script>alert(1)</script>", rendered.html)

    def test_password_reset_template_contains_secure_url_and_ignore_copy(self):
        rendered = render_email(
            "auth.password_reset",
            {"cta_url": "/reset-password?uid=abc&token=secret-token", "expiry_text": "This link expires soon."},
        )

        self.assertIn("Reset your SurePlace password", rendered.subject)
        self.assertIn("https://app.sureplace.test/reset-password?uid=abc&amp;token=secret-token", rendered.html)
        self.assertIn("If you did not request this", rendered.text)

    def test_verification_copy_is_scoped_and_no_document_urls_render(self):
        rendered = render_email(
            "verification.approved",
            {
                "message": "Identity verification approved.",
                "verification": {"type": "Identity", "status": "Approved"},
                "documents": [{"url": "https://private.example.test/document.pdf"}],
                "cta_url": "/account/verification/1",
            },
        )

        self.assertIn("stated verification type", rendered.html)
        self.assertNotIn("private.example.test", rendered.html)

    def test_saved_search_previews_limit_to_three(self):
        rendered = render_email(
            "alerts.saved_search_match",
            {
                **sample_context("alerts.saved_search_match"),
                "matches": [
                    {"title": "One", "location": "Mbabane", "price": "E1"},
                    {"title": "Two", "location": "Manzini", "price": "E2"},
                    {"title": "Three", "location": "Ezulwini", "price": "E3"},
                    {"title": "Four", "location": "Malkerns", "price": "E4"},
                ],
                "cta_url": "/saved-searches/1",
            },
        )

        self.assertIn("One", rendered.html)
        self.assertIn("Three", rendered.html)
        self.assertNotIn("Four", rendered.html)

    def test_notification_template_mapping(self):
        self.assertEqual(template_for_notification("BOOKING_CONFIRMED"), "booking.confirmed")
        self.assertEqual(
            template_for_notification("VERIFICATION_UPDATE", "Verification approved"), "verification.approved"
        )
        self.assertEqual(
            template_for_notification("VERIFICATION_UPDATE", "Verification rejected"), "verification.rejected"
        )
        self.assertEqual(template_for_notification("NEW_MESSAGE"), "messaging.new_message")

    def test_welcome_copy_is_not_repeated(self):
        rendered = render_email("auth.welcome", sample_context("auth.welcome"))
        self.assertEqual(rendered.html.count("save favourites"), 1)
        self.assertIn("Get started", rendered.html)
        self.assertIn("Search properties", rendered.html)

    def test_password_reset_has_no_internal_django_wording(self):
        rendered = render_email("auth.password_reset", sample_context("auth.password_reset"))
        combined = rendered.html + rendered.text
        self.assertNotIn("Django", combined)
        self.assertNotIn("token policy", combined)
        self.assertIn("For your security", combined)

    def test_booking_dates_are_human_friendly_and_reference_wraps(self):
        rendered = render_email(
            "booking.confirmed",
            {
                **sample_context("booking.confirmed"),
                "details": [
                    {"label": "Booking reference", "value": "SP-BKG-2026-AB12CD34EF"},
                    {"label": "Check-in", "value": "2026-10-12"},
                    {"label": "Check-out", "value": "2026-10-15"},
                    {"label": "Total", "value": "E3,600"},
                ],
            },
        )

        self.assertIn("12 Oct 2026", rendered.html)
        self.assertIn("15 Oct 2026", rendered.text)
        self.assertNotIn(">2026-10-12<", rendered.html)
        self.assertIn("overflow-wrap:anywhere", rendered.html)
        self.assertIn("SP-BKG-2026-AB12CD34EF", rendered.html)

    def test_booking_image_renders_when_available_and_fallback_works(self):
        with_image = render_email(
            "booking.confirmed",
            {
                **sample_context("booking.confirmed"),
                "stay": {
                    "name": "Royal Villas Guest House",
                    "location": "Ezulwini",
                    "image_url": "https://assets.sureplace.test/stays/royal-villas.jpg",
                },
            },
        )
        without_image = render_email("booking.confirmed", sample_context("booking.confirmed"))

        self.assertIn('src="https://assets.sureplace.test/stays/royal-villas.jpg"', with_image.html)
        self.assertIn('alt="Royal Villas Guest House"', with_image.html)
        self.assertNotIn("<img", without_image.html)
        self.assertIn("Royal Villas Guest House", without_image.html)

    def test_verification_copy_is_concise_and_scoped(self):
        rendered = render_email("verification.approved", sample_context("verification.approved"))
        combined = rendered.html + rendered.text

        self.assertEqual(combined.count("not a guarantee"), 2)
        self.assertIn("verification type", combined)
        self.assertNotIn("Verified Agent", combined)
        self.assertNotIn("Verified Property", combined)
