from rest_framework.test import APITestCase
from accounts.models import User
from properties.models import PropertyListing, ListingStatus
from stays.models import Stay, StayStatus, StayType
from .models import SavedSearch, SearchAlertEvent


class AlertTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="alert@example.com", password="StrongPass123!", first_name="A", last_name="U"
        )
        self.other = User.objects.create_user(
            email="alert2@example.com", password="StrongPass123!", first_name="B", last_name="U"
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
