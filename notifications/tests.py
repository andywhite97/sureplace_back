from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase
from accounts.models import User
from .models import EmailDelivery, Notification, NotificationPreference, NotificationType
from .services import create_notification, notify_transactional, send_transactional_email
from properties.models import ListingStatus, ListingType, PropertyListing, PropertyType


class NotificationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="notify@example.com", password="StrongPass123!", first_name="N", last_name="U"
        )
        self.other = User.objects.create_user(
            email="notify2@example.com", password="StrongPass123!", first_name="O", last_name="U"
        )

    def test_creation_dedup_preferences_and_safe_data(self):
        n = create_notification(
            self.user, NotificationType.SYSTEM, "Title", "Message", {"route": "/account", "secret": "no"}, "same"
        )
        self.assertEqual(
            create_notification(self.user, NotificationType.SYSTEM, "Title", "Message", event_key="same").id, n.id
        )
        self.assertNotIn("secret", n.data)
        p = NotificationPreference.objects.get(user=self.user)
        self.assertTrue(p.email_enabled)
        self.assertFalse(p.marketing_email)

    def test_preference_endpoint_persists_supported_fields(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            "/api/v1/notification-preferences/me/",
            {"new_message_email": False, "marketing_email": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        preference = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preference.new_message_email)
        self.assertTrue(preference.marketing_email)
        self.assertFalse(response.data["new_message_email"])
        self.assertTrue(response.data["marketing_email"])

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_disabled_category_suppresses_email_but_keeps_notification(self):
        NotificationPreference.objects.create(user=self.user, booking_updates_email=False)

        with self.captureOnCommitCallbacks(execute=True):
            notify_transactional(
                self.user,
                NotificationType.BOOKING_REQUESTED,
                "Booking requested",
                "A guest requested a booking.",
                {"route": "/account/bookings", "booking_id": "BK-disabled"},
                "booking:disabled",
                "booking_updates_email",
            )

        self.assertTrue(Notification.objects.filter(user=self.user, event_key="booking:disabled").exists())
        self.assertEqual(EmailDelivery.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_api_isolation_filters_and_read_actions(self):
        n = create_notification(self.user, NotificationType.NEW_MESSAGE, "Message", "Hello")
        create_notification(self.other, NotificationType.SYSTEM, "Other", "No")
        self.assertEqual(self.client.get("/api/notifications/").status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/notifications/").data["count"], 1)
        self.assertEqual(self.client.get("/api/notifications/unread-count/").data["unread_count"], 1)
        self.assertEqual(self.client.post(f"/api/notifications/{n.id}/mark-read/").status_code, 200)
        self.assertEqual(self.client.post("/api/notifications/mark-all-read/").status_code, 200)

    def test_listing_status_action_normalizes_legacy_approved_edit_route(self):
        listing = PropertyListing.objects.create(
            owner=self.user,
            title="Approved home",
            description="A published listing with enough detail. " * 4,
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=5000,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.305, "longitude": 31.136},
            status=ListingStatus.PUBLISHED,
        )
        notification = create_notification(
            self.user,
            NotificationType.LISTING_STATUS_UPDATE,
            "Listing approved",
            "Approved",
            {"route": f"/account/manage/properties/{listing.id}/edit", "status": "PUBLISHED"},
            "approved:legacy",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/notifications/{notification.id}/")
        self.assertEqual(response.data["action"], {"label": "View listing", "url": f"/properties/{listing.slug}"})

    def test_notification_action_rejects_external_route(self):
        notification = create_notification(
            self.user,
            NotificationType.SYSTEM,
            "Unsafe",
            "No",
            {"route": "https://evil.example/path"},
            "unsafe",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/notifications/{notification.id}/")
        self.assertIsNone(response.data["action"])

    def test_missing_property_target_falls_back_to_management(self):
        notification = create_notification(
            self.user,
            NotificationType.LISTING_STATUS_UPDATE,
            "Listing rejected",
            "Rejected",
            {"action": "PROPERTY_REJECTED", "property_id": "00000000-0000-0000-0000-000000000000"},
            "missing-property",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/notifications/{notification.id}/")
        self.assertEqual(response.data["action"]["url"], "/account/manage/properties")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_service(self):
        send_transactional_email(self.user.email, "SurePlace update", "Hello", "/account")
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[0].subject, "SurePlace update")

    @override_settings(
        EMAIL_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_notify_transactional_enqueues_email_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            notify_transactional(
                self.user,
                NotificationType.BOOKING_REQUESTED,
                "Booking requested",
                "A guest requested a booking.",
                {"route": "/account/bookings", "booking_id": "BK-1"},
                "booking:1",
                "booking_updates_email",
            )

        self.assertEqual(len(mail.outbox), 1)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.template_key, "booking.requested_host")
        self.assertEqual(delivery.status, EmailDelivery.Status.ACCEPTED)
