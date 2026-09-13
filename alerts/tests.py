from datetime import time, timedelta

from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User
from bookings.models import Booking, BookingStatus, ViewingRequest, ViewingStatus
from properties.models import PropertyListing, ListingStatus
from stays.models import RoomType, Stay, StayStatus, StayType
from verification.models import RequestStatus, VerificationRequest, VerificationType
from .models import SavedSearch, SearchAlertEvent


class AlertTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="alert@example.com", password="StrongPass123!", first_name="A", last_name="U",
            is_email_verified=True,
        )
        self.other = User.objects.create_user(
            email="alert2@example.com", password="StrongPass123!", first_name="B", last_name="U",
            is_email_verified=True,
        )
        self.client.force_authenticate(self.user)
        self.property = PropertyListing.objects.create(
            owner=self.user,
            title="Rental",
            description="D",
            listing_type="RENT",
            property_type="HOUSE",
            price=5000,
            region="Hhohho",
            town="Ezulwini",
            location={"latitude": -26.3, "longitude": 31.1},
            status=ListingStatus.PUBLISHED,
        )
        self.stay = Stay.objects.create(
            owner=self.user,
            name="Guest House",
            description="D",
            stay_type=StayType.GUEST_HOUSE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
        )

    def test_create_validate_generated_name_update_delete(self):
        response = self.client.post(
            "/api/saved-searches/",
            {"search_type": "PROPERTY", "criteria": {"listing_type": "RENT", "town": "Ezulwini", "min_price": 100}},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["name"])
        self.assertEqual(
            self.client.post(
                "/api/saved-searches/", {"search_type": "PROPERTY", "criteria": {"unknown": 1}}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(f"/api/saved-searches/{response.data['id']}/", {"frequency": "OFF"}, format="json").data[
                "notifications_enabled"
            ],
            False,
        )
        self.assertEqual(self.client.delete(f"/api/saved-searches/{response.data['id']}/").status_code, 204)

    def test_results_evaluation_dedup_and_last_checked(self):
        saved = SavedSearch.objects.create(
            user=self.user, name="Rentals", search_type="PROPERTY", criteria={"listing_type": "RENT"}
        )
        self.assertEqual(self.client.get(f"/api/saved-searches/{saved.id}/results/").data["count"], 1)
        first = self.client.post(f"/api/saved-searches/{saved.id}/check/")
        second = self.client.post(f"/api/saved-searches/{saved.id}/check/")
        self.assertEqual(first.data["new_matches"], 1)
        self.assertEqual(second.data["new_matches"], 0)
        saved.refresh_from_db()
        self.assertIsNotNone(saved.last_checked_at)

    def test_stay_results_owner_isolation_and_dashboard(self):
        saved = SavedSearch.objects.create(
            user=self.user, name="Stays", search_type="STAY", criteria={"stay_type": "GUEST_HOUSE"}
        )
        self.assertEqual(self.client.get(f"/api/saved-searches/{saved.id}/results/").data["count"], 1)
        SearchAlertEvent.objects.create(saved_search=saved, listing_type="STAY", stay=self.stay)
        summary = self.client.get("/api/dashboard/seeker-summary/").data
        self.assertEqual(summary["active_saved_searches"], 1)
        self.assertEqual(summary["new_alert_count"], 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/saved-searches/{saved.id}/").status_code, 404)

    def test_dashboard_returns_attention_and_lightweight_advertiser_context(self):
        today = timezone.localdate()
        viewing = ViewingRequest.objects.create(
            property=self.property,
            requester=self.user,
            requested_date=today + timedelta(days=1),
            requested_time=time(14, 0),
            status=ViewingStatus.CONFIRMED,
        )
        room = RoomType.objects.create(stay=self.stay, name="Double room", base_price=600)
        booking = Booking.objects.create(
            stay=self.stay,
            room_type=room,
            guest=self.user,
            check_in=today + timedelta(days=2),
            check_out=today + timedelta(days=4),
            adults=1,
            children=0,
            rooms=1,
            nightly_pricing=[],
            nightly_subtotal=1200,
            taxes=0,
            fees=0,
            total=1200,
            status=BookingStatus.CONFIRMED,
            guest_name="A U",
            guest_email=self.user.email,
        )
        verification = VerificationRequest.objects.create(
            applicant=self.user,
            verification_type=VerificationType.IDENTITY,
            status=RequestStatus.CHANGES_REQUESTED,
            reviewer_notes="Upload a clearer identity document.",
        )

        summary = self.client.get("/api/dashboard/seeker-summary/")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["next_viewing"]["id"], str(viewing.id))
        self.assertEqual(summary.data["next_stay"]["id"], str(booking.id))
        self.assertEqual(str(summary.data["verification_attention"][0]["id"]), str(verification.id))
        self.assertEqual(summary.data["advertiser_summary"]["published_property_count"], 1)
        self.assertEqual(summary.data["advertiser_summary"]["published_stay_count"], 1)
