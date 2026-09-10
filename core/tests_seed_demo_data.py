import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from agencies.models import Agency
from alerts.models import SavedSearch
from alerts.services import matches
from bookings.models import Booking, BookingStatus, ViewingRequest
from favourites.models import Favourite
from messaging.models import Conversation, Message, MessageType
from notifications.models import EmailDelivery, Notification
from properties.models import ListingStatus, PropertyImage, PropertyListing
from stays.models import RoomAvailability, RoomType, Stay, StayStatus
from verification.models import RequestStatus, VerificationRequest, VerificationType


@override_settings(DEBUG=True, USE_SQLITE=True, MEDIA_ROOT=tempfile.mkdtemp())
class SeedDemoDataTests(TestCase):
    def seed(self, *args):
        call_command("seed_demo_data", *args, verbosity=0)

    def test_seed_demo_data_is_realistic_idempotent_and_side_effect_safe(self):
        self.seed("--reset")
        first = self.counts()
        self.seed()
        self.assertEqual(self.counts(), first)
        self.assertEqual(first["properties"], 30)
        self.assertEqual(first["stays"], 20)
        self.assertEqual(first["users"], 12)
        self.assertEqual(first["bookings"], 12)
        self.assertEqual(first["viewings"], 12)
        self.assertEqual(first["email_deliveries"], 0)

        for town in ["Mbabane", "Manzini", "Ezulwini", "Matsapha", "Lobamba", "Siteki"]:
            self.assertGreaterEqual(
                PropertyListing.objects.filter(
                    slug__startswith="demo-", status=ListingStatus.PUBLISHED, town=town
                ).count(),
                2,
            )
            self.assertGreaterEqual(
                Stay.objects.filter(slug__startswith="demo-", status=StayStatus.PUBLISHED, town=town).count(),
                1,
            )

        self.assertEqual(
            PropertyListing.objects.filter(slug__startswith="demo-").values("slug").distinct().count(),
            PropertyListing.objects.filter(slug__startswith="demo-").count(),
        )
        self.assertEqual(
            Stay.objects.filter(slug__startswith="demo-").values("slug").distinct().count(),
            Stay.objects.filter(slug__startswith="demo-").count(),
        )
        for listing in PropertyListing.objects.filter(slug__startswith="demo-", status=ListingStatus.PUBLISHED):
            self.assertIsNotNone(listing.latitude)
            self.assertIsNotNone(listing.longitude)
            self.assertGreaterEqual(listing.latitude, -28.0)
            self.assertLessEqual(listing.latitude, -25.0)
            self.assertGreaterEqual(listing.longitude, 30.5)
            self.assertLessEqual(listing.longitude, 32.5)
            self.assertEqual(listing.images.filter(is_cover=True).count(), 1)
            self.assertGreaterEqual(listing.images.count(), 3)
        for stay in Stay.objects.filter(slug__startswith="demo-", status=StayStatus.PUBLISHED):
            self.assertIsNotNone(stay.latitude)
            self.assertIsNotNone(stay.longitude)
            self.assertEqual(stay.images.filter(is_cover=True).count(), 1)
            self.assertGreaterEqual(stay.images.count(), 3)

        self.assertTrue(SavedSearch.objects.filter(user__email__endswith="@demo.sureplace.local").exists())
        self.assertTrue(any(matches(saved).exists() for saved in SavedSearch.objects.all()))
        self.assertGreater(Favourite.objects.filter(user__email__endswith="@demo.sureplace.local").count(), 0)
        self.assertGreater(
            Notification.objects.filter(user__email__endswith="@demo.sureplace.local", is_read=False).count(), 0
        )
        self.assertGreater(Conversation.objects.filter(created_by__email__endswith="@demo.sureplace.local").count(), 0)
        self.assertTrue(Message.objects.filter(message_type=MessageType.SYSTEM, sender__isnull=True).exists())
        self.assertFalse(Message.objects.filter(message_type=MessageType.SYSTEM, sender__isnull=False).exists())

        self.assertEqual(
            set(ViewingRequest.objects.values_list("status", flat=True)).issuperset(
                {"PENDING", "CONFIRMED", "DECLINED", "CANCELLED"}
            ),
            True,
        )
        self.assertEqual(set(Booking.objects.values_list("status", flat=True)), set(BookingStatus.values))
        for booking in Booking.objects.all():
            self.assertGreater(booking.check_out, booking.check_in)
            self.assertEqual(booking.total, booking.nightly_subtotal + booking.taxes + booking.fees)
        self.assert_no_inventory_oversell()

        self.assertTrue(
            VerificationRequest.objects.filter(
                verification_type=VerificationType.AGENT, status=RequestStatus.APPROVED
            ).exists()
        )
        self.assertTrue(
            VerificationRequest.objects.filter(
                verification_type=VerificationType.PROPERTY, status=RequestStatus.REJECTED
            ).exists()
        )
        verified_agent = VerificationRequest.objects.get(
            verification_type=VerificationType.AGENT, status=RequestStatus.APPROVED
        ).agent_profile
        self.assertTrue(
            PropertyListing.objects.filter(agent=verified_agent).exclude(verification_status="VERIFIED").exists()
        )

    def test_reset_removes_only_demo_data(self):
        User = get_user_model()
        real_user = User.objects.create_user(
            email="real@example.com",
            password="RealPass123!",
            first_name="Real",
            last_name="User",
        )
        self.seed("--reset")
        self.assertTrue(User.objects.filter(pk=real_user.pk).exists())
        self.assertEqual(User.objects.filter(email__endswith="@demo.sureplace.local").count(), 12)
        self.assertFalse(PropertyListing.objects.exclude(slug__startswith="demo-").exists())

    def test_count_flag_keeps_sixty_forty_listing_split(self):
        self.seed("--reset", "--count", "20", "--seed", "99")
        self.assertEqual(PropertyListing.objects.filter(slug__startswith="demo-").count(), 12)
        self.assertEqual(Stay.objects.filter(slug__startswith="demo-").count(), 8)

    def counts(self):
        return {
            "users": get_user_model().objects.filter(email__endswith="@demo.sureplace.local").count(),
            "properties": PropertyListing.objects.filter(slug__startswith="demo-").count(),
            "stays": Stay.objects.filter(slug__startswith="demo-").count(),
            "property_images": PropertyImage.objects.filter(property__slug__startswith="demo-").count(),
            "room_types": RoomType.objects.filter(stay__slug__startswith="demo-").count(),
            "availability": RoomAvailability.objects.filter(room_type__stay__slug__startswith="demo-").count(),
            "bookings": Booking.objects.filter(guest__email__endswith="@demo.sureplace.local").count(),
            "viewings": ViewingRequest.objects.filter(requester__email__endswith="@demo.sureplace.local").count(),
            "email_deliveries": EmailDelivery.objects.filter(recipient__endswith="@demo.sureplace.local").count(),
            "agencies": Agency.objects.filter(slug__startswith="demo-").count(),
        }

    def assert_no_inventory_oversell(self):
        today = timezone.localdate()
        for room in RoomType.objects.filter(stay__slug__startswith="demo-"):
            for offset in range(-30, 91):
                day = today + timedelta(days=offset)
                active_rooms = sum(
                    booking.rooms
                    for booking in room.bookings.filter(
                        status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
                        check_in__lte=day,
                        check_out__gt=day,
                    )
                )
                self.assertLessEqual(active_rooms, room.quantity)
