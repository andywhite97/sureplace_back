from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch
from rest_framework.test import APIClient
from accounts.models import User
from notifications.models import NotificationPreference
from stays.models import Stay, StayStatus, StayType, RoomType, RoomAvailability
from .models import Booking, BookingStatus, ViewingRequest
from .serializers import BookingSerializer, ViewingSerializer
from .services import create_booking, expire_pending, inventory, transition


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class BookingTests(TestCase):
    def test_expiry_survives_a_removed_conversation(self):
        booking = self.create()
        booking.conversation = None
        booking.expires_at = timezone.now() - timedelta(minutes=1)
        booking.save(update_fields=["conversation", "expires_at"])
        self.assertEqual(expire_pending(), 1)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.EXPIRED)
        self.assertTrue(booking.events.filter(status=BookingStatus.EXPIRED).exists())
        self.assertEqual(inventory(self.room, self.start), self.room.quantity)

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

    def test_instant_booking_reserves_inventory_and_snapshots_policies(self):
        from stays.models import BookingMode

        self.stay.booking_mode = BookingMode.INSTANT_BOOK
        self.stay.cancellation_policy = "Cancel at least two days before arrival."
        self.stay.save()
        b = self.create(idempotency_key="instant")
        self.assertEqual(b.status, BookingStatus.CONFIRMED)
        self.assertIsNone(b.expires_at)
        self.assertIsNotNone(b.confirmed_at)
        self.assertEqual(inventory(self.room, self.start), 1)
        self.assertEqual(self.create(idempotency_key="instant").pk, b.pk)
        self.stay.cancellation_policy = "Changed terms"
        self.stay.save()
        b.refresh_from_db()
        self.assertEqual(b.policy_snapshot["cancellation_policy"], "Cancel at least two days before arrival.")
        self.assertEqual(b.events.get().status, BookingStatus.CONFIRMED)

    def test_quote_conflict_requires_acknowledgement_without_reserving_inventory(self):
        client = self.api_client(self.guest)
        payload = self.payload(expected_total="1600.00")
        response = client.post(f"/api/v1/stays/{self.stay.pk}/bookings/", payload, format="json", HTTP_IDEMPOTENCY_KEY="price-review")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "price_changed")
        self.assertEqual(response.data["new_total"], "1700.00")
        self.assertFalse(Booking.objects.exists())
        payload["expected_total"] = response.data["new_total"]
        response = client.post(f"/api/v1/stays/{self.stay.pk}/bookings/", payload, format="json", HTTP_IDEMPOTENCY_KEY="price-review")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Booking.objects.count(), 1)

    def test_policy_consent_required_by_api(self):
        client = self.api_client(self.guest)
        for consent in (False, None):
            payload = self.payload()
            if consent is None:
                payload.pop("policies_accepted")
            else:
                payload["policies_accepted"] = consent
            self.assertEqual(client.post(f"/api/v1/stays/{self.stay.pk}/bookings/", payload, format="json").status_code, 400)

    def test_decline_and_operator_cancel_preserve_reasons_and_audit_events(self):
        b = self.create()
        with self.assertRaises(ValidationError):
            transition(b, BookingStatus.DECLINED, self.host)
        b = transition(b, BookingStatus.DECLINED, self.host, reason="CANNOT_ACCOMMODATE", note="Accessibility request cannot be met.")
        self.assertEqual(b.decline_reason, "CANNOT_ACCOMMODATE")
        self.assertEqual(b.events.filter(status=BookingStatus.DECLINED).get().actor_id, self.host.pk)
        self.assertEqual(inventory(self.room, self.start), 2)
        b = transition(self.create(), BookingStatus.CONFIRMED, self.host)
        with self.assertRaises(ValidationError):
            transition(b, BookingStatus.CANCELLED, self.host)
        b = transition(b, BookingStatus.CANCELLED, self.host, reason="Property unavailable")
        self.assertEqual(b.cancellation_reason, "Property unavailable")
        self.assertEqual(inventory(self.room, self.start), 2)

    def test_expiry_and_guest_cancellation_notify_correct_recipients(self):
        from notifications.models import Notification, NotificationType

        for user in (self.host, self.guest):
            NotificationPreference.objects.create(user=user, email_enabled=False)
        b = self.create()
        with self.captureOnCommitCallbacks(execute=True):
            transition(b, BookingStatus.CANCELLED, self.guest, reason="Plans changed")
        self.assertTrue(Notification.objects.filter(user=self.host, notification_type=NotificationType.BOOKING_CANCELLED).exists())
        b = self.create()
        b.expires_at = timezone.now() - timedelta(minutes=1)
        b.save()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(expire_pending(), 1)
        self.assertTrue(Notification.objects.filter(user=self.guest, notification_type=NotificationType.BOOKING_EXPIRED).exists())

    def test_guest_scope_excludes_hosted_bookings_and_room_calendar_is_private(self):
        b = self.create()
        host = self.api_client(self.host)
        self.assertEqual(host.get("/api/v1/bookings/?scope=guest").data["results"], [])
        self.assertEqual(host.get("/api/v1/bookings/?scope=manager").data["count"], 1)
        endpoint = f"/api/v1/rooms/{self.room.pk}/calendar/?start={self.start}&end={self.start}"
        self.assertEqual(self.api_client(self.guest).get(endpoint).status_code, 403)
        response = host.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["reserved_units"], 1)

    def test_availability_explains_unavailable_room_types(self):
        self.room.minimum_stay = 3
        self.room.save()
        endpoint = f"/api/v1/stays/{self.stay.pk}/availability/?check_in={self.start}&check_out={self.start+timedelta(days=2)}&include_unavailable=true"
        response = APIClient().get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["room_types"][0]["available"])
        self.assertEqual(response.data["room_types"][0]["reason"], "minimum_stay")
        self.assertEqual(response.data["room_types"][0]["minimum_stay"], 3)

    def test_bulk_inventory_changes_cannot_remove_reserved_units(self):
        self.create(rooms=2)
        payload = {"start_date": str(self.start), "end_date": str(self.start), "available_units": 1}
        response = self.api_client(self.host).post(f"/api/v1/rooms/{self.room.pk}/availability/bulk/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.room.availability.exists())
        response = self.api_client(self.host).patch(f"/api/v1/rooms/{self.room.pk}/", {"quantity": 1}, format="json")
        self.assertEqual(response.status_code, 400)
        self.room.refresh_from_db()
        self.assertEqual(self.room.quantity, 2)

    def test_idempotency_lookup_is_scoped_to_the_current_guest(self):
        b = self.create(idempotency_key="recovery-key")
        endpoint = "/api/v1/bookings/?scope=guest&idempotency_key=recovery-key"
        self.assertEqual(self.api_client(self.guest).get(endpoint).data["results"][0]["id"], str(b.id))
        self.assertEqual(self.api_client(self.other).get(endpoint).data["results"], [])
        self.assertEqual(self.api_client(self.host).get(endpoint).data["results"], [])

    def test_upcoming_reminders_are_deduplicated(self):
        from notifications.models import Notification, NotificationType
        from notifications.tasks import upcoming_booking_reminders

        for user in (self.host, self.guest):
            NotificationPreference.objects.create(user=user, email_enabled=False)
        tomorrow = timezone.localdate() + timedelta(days=1)
        b = self.create(check_in=tomorrow, check_out=tomorrow+timedelta(days=2))
        transition(b, BookingStatus.CONFIRMED, self.host)
        with self.captureOnCommitCallbacks(execute=True):
            upcoming_booking_reminders()
            upcoming_booking_reminders()
        self.assertEqual(Notification.objects.filter(notification_type=NotificationType.BOOKING_REMINDER).count(), 2)

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
        with patch("bookings.services.timezone.localdate", return_value=b.check_out):
            b = transition(b, BookingStatus.COMPLETED, self.host)
        self.assertEqual(b.status, BookingStatus.COMPLETED)

    def api_client(self, user):
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified"])
        client = APIClient()
        client.force_authenticate(user)
        return client

    def payload(self, **changes):
        data = {
            "room_type": str(self.room.pk),
            "check_in": self.start.isoformat(),
            "check_out": (self.start + timedelta(days=2)).isoformat(),
            "guest_name": "Guest",
            "guest_email": self.guest.email,
            "policies_accepted": True,
        }
        return {**data, **changes}

    def test_invalid_inputs_do_not_create_bookings_or_consume_inventory(self):
        client = self.api_client(self.guest)
        invalid = [
            {"rooms": 0}, {"rooms": -1}, {"rooms": "invalid"}, {"rooms": 1.5},
            {"adults": 0}, {"children": -1}, {"adults": 32768},
            {"guest_name": "   "}, {"guest_name": "x" * 201},
            {"guest_email": "not-an-email"}, {"guest_phone": "x" * 21},
            {"check_in": "not-a-date"},
            {"check_in": (timezone.localdate() - timedelta(days=1)).isoformat()},
            {"check_out": self.start.isoformat()},
            {"room_type": "invalid"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = client.post(f"/api/v1/stays/{self.stay.pk}/bookings/", self.payload(**changes), format="json")
                self.assertEqual(response.status_code, 400, response.data)
        response = client.post(f"/api/v1/stays/{self.stay.pk}/bookings/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Booking.objects.exists())
        self.assertEqual(inventory(self.room, self.start), 2)

    def test_unknown_or_wrong_stay_room_returns_not_found(self):
        import uuid

        client = self.api_client(self.guest)
        endpoint = f"/api/v1/stays/{self.stay.pk}/bookings/"
        self.assertEqual(client.post(endpoint, self.payload(room_type=str(uuid.uuid4())), format="json").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/stays/{uuid.uuid4()}/bookings/", self.payload(), format="json").status_code, 404)
        other_stay = Stay.objects.create(owner=self.host, name="Other", stay_type=StayType.LODGE)
        self.room.stay = other_stay
        self.room.save()
        self.assertEqual(client.post(endpoint, self.payload(), format="json").status_code, 404)

    def test_service_also_rejects_invalid_contact_counts_and_past_dates(self):
        for changes in (
            {"guest_name": "   "}, {"guest_email": "invalid"},
            {"rooms": 0}, {"adults": 0}, {"children": -1},
            {"check_in": timezone.localdate() - timedelta(days=1)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.create(**changes)
        self.assertFalse(Booking.objects.exists())

    def test_only_active_managers_can_read_booking_contacts(self):
        from agencies.models import Agency, AgentProfile

        agency = Agency.objects.create(name="Booking agency", slug="booking-agency")
        agent = AgentProfile.objects.create(user=self.other, agency=agency, is_active=True)
        self.stay.agency = agency
        self.stay.agent = agent
        self.stay.save()
        b = self.create()
        client = self.api_client(self.other)
        self.assertEqual(client.get(f"/api/v1/bookings/{b.pk}/").status_code, 200)
        agent.is_active = False
        agent.save()
        self.assertEqual(client.get(f"/api/v1/bookings/{b.pk}/").status_code, 404)
        for scope in ("", "?scope=manager"):
            self.assertEqual(client.get(f"/api/v1/bookings/{scope}").data["results"], [])
        self.assertEqual(client.post(f"/api/v1/bookings/{b.pk}/confirm/").status_code, 404)
        self.assertEqual(self.api_client(self.host).get(f"/api/v1/bookings/{b.pk}/").status_code, 200)
        self.assertEqual(self.api_client(self.guest).get(f"/api/v1/bookings/{b.pk}/").status_code, 200)

    def test_expired_hold_releases_inventory_without_waiting_for_scheduler(self):
        b = self.create(rooms=2)
        b.expires_at = timezone.now() - timedelta(seconds=1)
        b.save()
        self.assertEqual(inventory(self.room, self.start), 2)
        replacement = self.create(guest=self.other, guest_email=self.other.email, rooms=2)
        with self.assertRaisesMessage(ValidationError, "expired"):
            transition(b, BookingStatus.CONFIRMED, self.host)
        self.assertEqual(inventory(self.room, self.start), 0)
        self.assertEqual(transition(replacement, BookingStatus.CONFIRMED, self.host).status, BookingStatus.CONFIRMED)
        self.assertEqual(expire_pending(), 1)

    def test_future_completion_is_rejected_and_inventory_stays_reserved(self):
        b = transition(self.create(), BookingStatus.CONFIRMED, self.host)
        with self.assertRaisesMessage(ValidationError, "check-out"):
            transition(b, BookingStatus.COMPLETED, self.host)
        b.refresh_from_db()
        self.assertEqual(b.status, BookingStatus.CONFIRMED)
        self.assertEqual(inventory(self.room, self.start), 1)

    def test_booking_notifications_link_to_existing_guest_and_manager_routes(self):
        from notifications.models import Notification, NotificationType
        from notifications.serializers import NotificationSerializer

        NotificationPreference.objects.create(user=self.host, email_enabled=False)
        NotificationPreference.objects.create(user=self.guest, email_enabled=False)
        with self.captureOnCommitCallbacks(execute=True):
            b = self.create()
        requested = Notification.objects.get(notification_type=NotificationType.BOOKING_REQUESTED, user=self.host)
        self.assertEqual(requested.data["route"], f"/account/manage/bookings/{b.pk}")
        requested.data["route"] = f"/bookings/{b.pk}"
        self.assertEqual(NotificationSerializer(requested).data["action"]["url"], "/account/manage/bookings")
        with self.captureOnCommitCallbacks(execute=True):
            transition(b, BookingStatus.CONFIRMED, self.host)
        confirmed = Notification.objects.get(notification_type=NotificationType.BOOKING_CONFIRMED, user=self.guest)
        self.assertEqual(confirmed.data["route"], f"/account/bookings/{b.pk}")
        confirmed.data["route"] = f"/account/bookings/{b.pk}"
        self.assertEqual(NotificationSerializer(confirmed).data["action"]["url"], f"/account/bookings/{b.pk}")

    def test_inactive_assigned_agent_does_not_receive_booking_notifications(self):
        from agencies.models import Agency, AgentProfile
        from notifications.models import Notification, NotificationType

        agency = Agency.objects.create(name="Inactive agency", slug="inactive-agency")
        agent = AgentProfile.objects.create(user=self.other, agency=agency, is_active=False)
        self.stay.agency = agency
        self.stay.agent = agent
        self.stay.save()
        NotificationPreference.objects.create(user=self.host, email_enabled=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.create()
        requested = Notification.objects.get(notification_type=NotificationType.BOOKING_REQUESTED)
        self.assertEqual(requested.user_id, self.host.pk)

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
            "policies_accepted": True,
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
