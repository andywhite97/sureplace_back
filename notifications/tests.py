from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase
from accounts.models import User
from .models import EmailDelivery, NotificationPreference, NotificationType
from .services import create_notification, notify_transactional, send_transactional_email


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

    def test_api_isolation_filters_and_read_actions(self):
        n = create_notification(self.user, NotificationType.NEW_MESSAGE, "Message", "Hello")
        create_notification(self.other, NotificationType.SYSTEM, "Other", "No")
        self.assertEqual(self.client.get("/api/notifications/").status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/notifications/").data["count"], 1)
        self.assertEqual(self.client.get("/api/notifications/unread-count/").data["unread_count"], 1)
        self.assertEqual(self.client.post(f"/api/notifications/{n.id}/mark-read/").status_code, 200)
        self.assertEqual(self.client.post("/api/notifications/mark-all-read/").status_code, 200)

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
        self.assertEqual(delivery.template_key, NotificationType.BOOKING_REQUESTED.lower())
        self.assertEqual(delivery.status, EmailDelivery.Status.ACCEPTED)
