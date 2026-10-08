from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from properties.models import AvailabilityStatus, ListingStatus
from properties.services import confirm_availability
from properties.tests import make_listing
from .tasks import property_availability_reminders


@override_settings(PROPERTY_AVAILABILITY_REMINDER_DAYS=14, PROPERTY_AVAILABILITY_STALE_DAYS=21)
class AvailabilityLifecycleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="availability@example.com", password="StrongPass123!", first_name="Availability", last_name="Owner", is_email_verified=True)
        self.now = timezone.now()
        self.property = make_listing(
            self.owner, status=ListingStatus.PUBLISHED,
            availability_status=AvailabilityStatus.AVAILABLE,
            availability_confirmed_at=self.now - timedelta(days=14),
        )

    @patch("notifications.tasks.notify_transactional")
    def test_reminds_once_at_fourteen_days_and_expires_at_twenty_one(self, notify):
        with patch("notifications.tasks.timezone.now", return_value=self.now):
            self.assertEqual(property_availability_reminders(), 1)
            self.assertEqual(property_availability_reminders(), 0)
        self.property.refresh_from_db()
        self.assertEqual(self.property.availability_status, AvailabilityStatus.AVAILABLE)
        self.assertEqual(notify.call_count, 1)
        self.property.availability_confirmed_at = self.now - timedelta(days=21)
        self.property.save(update_fields=["availability_confirmed_at"])
        with patch("notifications.tasks.timezone.now", return_value=self.now):
            self.assertEqual(property_availability_reminders(), 1)
            self.assertEqual(property_availability_reminders(), 0)
        self.property.refresh_from_db()
        self.assertEqual(self.property.availability_status, AvailabilityStatus.UNAVAILABLE)
        self.assertEqual(self.property.status, ListingStatus.PUBLISHED)
        self.assertEqual(notify.call_count, 2)

    @patch("notifications.tasks.notify_transactional")
    def test_confirmation_restarts_timer_and_restores_availability(self, notify):
        self.property.availability_status = AvailabilityStatus.UNAVAILABLE
        self.property.availability_reminded_at = self.now
        self.property.save()
        confirm_availability(self.property)
        self.assertIsNone(self.property.availability_reminded_at)
        self.assertEqual(self.property.availability_status, AvailabilityStatus.AVAILABLE)
        self.assertEqual(property_availability_reminders(), 0)
        notify.assert_not_called()

    @patch("notifications.tasks.notify_transactional")
    def test_paused_and_recent_properties_are_not_reminded(self, notify):
        self.property.status = ListingStatus.PAUSED
        self.property.save()
        make_listing(self.owner, title="Recent", status=ListingStatus.PUBLISHED,
                     availability_status=AvailabilityStatus.AVAILABLE, availability_confirmed_at=self.now)
        self.assertEqual(property_availability_reminders(), 0)
        notify.assert_not_called()

    @patch("notifications.tasks.notify_transactional")
    def test_legacy_unconfirmed_available_property_expires_from_publication(self, notify):
        self.property.availability_confirmed_at = None
        self.property.published_at = self.now - timedelta(days=21)
        self.property.save()
        with patch("notifications.tasks.timezone.now", return_value=self.now):
            self.assertEqual(property_availability_reminders(), 1)
        self.property.refresh_from_db()
        self.assertEqual(self.property.availability_status, AvailabilityStatus.UNAVAILABLE)
