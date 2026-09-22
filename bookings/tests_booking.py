from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch
from rest_framework.test import APIClient
from accounts.models import User
from notifications.models import NotificationPreference
from stays.models import Stay, StayStatus, StayType, RoomType, RoomAvailability
from .models import BookingStatus, ViewingRequest
from .serializers import BookingSerializer, ViewingSerializer
from .services import create_booking, expire_pending, inventory, transition


class BookingTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user(
            email="hostb@example.com", password="StrongPass123!", first_name="H", last_name="O"
        )
        self.guest = User.objects.create_user(
            email="guestb@example.com", password="StrongPass123!", first_name="G", last_name="U"
        )
        self.other = User.objects.create_user(
            email="otherb@example.com", password="StrongPass123!", first_name="O", last_name="U"
        )
        self.stay = Stay.objects.create(
            owner=self.host,
            name="Book Lodge",
            description="D",
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
        )
        self.room = RoomType.objects.create(
            stay=self.stay,
            name="Double",
            capacity_adults=2,
            capacity_children=1,
            total_capacity=3,
            quantity=2,
            base_price=850,
            minimum_stay=1,
        )
        self.start = date.today() + timedelta(days=10)

    def create(self, **kw):
        data = dict(
            guest=self.guest,
            stay=self.stay,
            room_type=self.room,
            check_in=self.start,
            check_out=self.start + timedelta(days=2),
            adults=2,
            children=0,
            rooms=1,
            guest_name="Guest",
            guest_email="guestb@example.com",
        )
        data.update(kw)
        return create_booking(**data)

    def test_pricing_snapshot_multiple_rooms_and_idempotency(self):
        RoomAvailability.objects.create(room_type=self.room, date=self.start, available_units=2, custom_price=950)
        b = self.create(rooms=2, idempotency_key="same")
        self.assertEqual(b.total, 3600)
        self.assertEqual(len(b.nightly_pricing), 2)
        self.assertEqual(self.create(rooms=2, idempotency_key="same").id, b.id)

    def test_inventory_status_release_and_expiry(self):
        b = self.create()
        self.assertEqual(inventory(self.room, self.start), 1)
        transition(b, BookingStatus.CANCELLED, self.guest)
        self.assertEqual(inventory(self.room, self.start), 2)
        stale = self.create()
        stale.expires_at = timezone.now() - timedelta(minutes=1)
        stale.save()
        self.assertEqual(expire_pending(), 1)
        self.assertEqual(inventory(self.room, self.start), 2)

    def test_insufficient_blocked_occupancy_minimum_and_self_booking(self):
        self.create(rooms=2)
        with self.assertRaises(ValidationError):
            self.create()
        with self.assertRaises(ValidationError):
            self.create(guest=self.host, guest_email="hostb@example.com")
        with self.assertRaises(ValidationError):
            self.create(adults=3)

    def test_manager_workflow_permissions(self):
        b = self.create()
        with self.assertRaises(ValidationError):
            transition(b, BookingStatus.CONFIRMED, self.guest)
        b = transition(b, BookingStatus.CONFIRMED, self.host)
        self.assertEqual(b.status, BookingStatus.CONFIRMED)
        b = transition(b, BookingStatus.COMPLETED, self.host)
        self.assertEqual(b.status, BookingStatus.COMPLETED)

    def test_booking_serializer_exposes_stay_context(self):
        b = self.create()
        data = BookingSerializer(b).data
        self.assertEqual(data["stay_name"], "Book Lodge")
        self.assertEqual(data["stay_slug"], self.stay.slug)
        self.assertEqual(data["stay_town"], "Mbabane")
        self.assertIn("stay_image", data)

    def test_notification_delivery_failure_does_not_fail_booking(self):
        NotificationPreference.objects.create(user=self.host)
        with patch(
            "notifications.services.enqueue_transactional_email",
            side_effect=RuntimeError("email queue unavailable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                booking = self.create()

        self.assertEqual(booking.status, BookingStatus.PENDING)
        self.assertTrue(type(booking).objects.filter(pk=booking.pk).exists())

    def test_booking_endpoint_returns_created_when_notification_queue_is_unavailable(self):
        self.guest.is_email_verified = True
        self.guest.save(update_fields=["is_email_verified"])
        NotificationPreference.objects.create(user=self.host)
        client = APIClient()
        client.force_authenticate(self.guest)
        payload = {
            "room_type": str(self.room.id),
            "check_in": self.start.isoformat(),
            "check_out": (self.start + timedelta(days=2)).isoformat(),
            "adults": 2,
            "children": 0,
            "rooms": 1,
            "guest_name": "Guest User",
            "guest_email": self.guest.email,
            "guest_phone": "",
            "special_requests": "",
        }

        with patch(
            "notifications.services.enqueue_transactional_email",
            side_effect=RuntimeError("email queue unavailable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = client.post(
                    f"/api/v1/stays/{self.stay.id}/bookings/",
                    payload,
                    format="json",
                    HTTP_IDEMPOTENCY_KEY="booking-api-regression",
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], BookingStatus.PENDING)

    def test_viewing_serializer_exposes_property_context(self):
        from properties.models import ListingStatus, ListingType, PropertyListing, PropertyType

        prop = PropertyListing.objects.create(
            owner=self.host,
            title="Viewing House",
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=5000,
            region="Hhohho",
            town="Mbabane",
            suburb="Sidwashini",
            status=ListingStatus.PUBLISHED,
        )
        viewing = ViewingRequest.objects.create(
            property=prop,
            requester=self.guest,
            requested_date=self.start,
            requested_time="12:00",
        )
        data = ViewingSerializer(viewing).data
        self.assertEqual(data["property_title"], "Viewing House")
        self.assertEqual(data["requester_display_name"], "G U")
        self.assertEqual(data["property_slug"], prop.slug)
        self.assertEqual(data["property_town"], "Mbabane")
        self.assertIn("property_image", data)
