from datetime import date, timedelta
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from accounts.models import User
from .models import *
from .services import room_availability


class StayPhaseTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="host@example.com", password="StrongPass123!", first_name="Host", last_name="One"
        )
        self.other = User.objects.create_user(
            email="otherstay@example.com", password="StrongPass123!", first_name="Other", last_name="One"
        )
        self.stay = Stay.objects.create(
            owner=self.owner,
            name="Mountain Lodge",
            description="Lovely mountain accommodation. " * 5,
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
            featured=True,
        )
        self.room = RoomType.objects.create(
            stay=self.stay,
            name="Deluxe Room",
            capacity_adults=2,
            capacity_children=1,
            total_capacity=3,
            quantity=3,
            base_price="850",
            minimum_stay=1,
        )

    def test_ids_slug_and_public_visibility(self):
        other = Stay.objects.create(owner=self.owner, name="Mountain Lodge", stay_type=StayType.LODGE)
        self.assertNotEqual(self.stay.slug, other.slug)
        self.assertNotEqual(self.stay.public_id, other.public_id)
        self.assertEqual(self.client.get("/api/stays/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/stays/{self.stay.slug}/").status_code, 200)

    def test_authenticated_creation_and_permissions(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/stays/",
            {"name": "New Stay", "stay_type": "HOTEL", "latitude": -26.2, "longitude": 31.2},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.patch(f"/api/stays/{self.stay.id}/", {"name": "No"}, format="json").status_code, 403
        )

    def test_featured_search_and_bounds(self):
        self.assertEqual(self.client.get("/api/stays/featured/").data["count"], 1)
        self.assertEqual(self.client.get("/api/stays/", {"search": "Mountain"}).data["count"], 1)

    def test_image_order_and_cover(self):
        a = StayImage.objects.create(stay=self.stay, image="a.jpg", sort_order=2, is_cover=True)
        b = StayImage.objects.create(stay=self.stay, image="b.jpg", sort_order=1, is_cover=True)
        a.refresh_from_db()
        self.assertFalse(a.is_cover)
        self.assertEqual(list(self.stay.images.all()), [b, a])
        x = RoomTypeImage.objects.create(room_type=self.room, image="x.jpg", sort_order=2, is_cover=True)
        y = RoomTypeImage.objects.create(room_type=self.room, image="y.jpg", sort_order=1, is_cover=True)
        x.refresh_from_db()
        self.assertFalse(x.is_cover)
        self.assertEqual(list(self.room.images.all()), [y, x])

    def test_room_validation_and_effective_price(self):
        bad = RoomType(stay=self.stay, name="Bad", base_price=-1, minimum_stay=0, total_capacity=0, capacity_adults=1)
        self.assertRaises(ValidationError, bad.full_clean)
        day = date.today() + timedelta(days=1)
        RoomAvailability.objects.create(room_type=self.room, date=day, available_units=2, custom_price="1200")
        self.assertEqual(str(self.room.effective_price(day)), "1200.00")

    def test_availability_rules_and_total(self):
        start = date.today() + timedelta(days=10)
        RoomAvailability.objects.create(room_type=self.room, date=start, available_units=2, custom_price="1000")
        result = room_availability(self.room, start, start + timedelta(days=2), 2, 1, 1)
        self.assertTrue(result["available"])
        self.assertEqual(result["total"], "1850.00")
        row = self.room.availability.get(date=start)
        row.is_blocked = True
        row.save()
        self.assertFalse(room_availability(self.room, start, start + timedelta(days=2), 2, 1, 1)["available"])
        self.assertFalse(room_availability(self.room, start, start + timedelta(days=2), 8, 0, 1)["available"])
        with self.assertRaises(ValidationError):
            room_availability(self.room, start, start, 1, 0, 1)

    def test_availability_endpoint_and_bulk_management(self):
        start = date.today() + timedelta(days=20)
        params = {"check_in": start, "check_out": start + timedelta(days=2), "adults": 2, "children": 0, "rooms": 1}
        self.assertEqual(len(self.client.get(f"/api/stays/{self.stay.id}/availability/", params).data["room_types"]), 1)
        self.client.force_authenticate(self.owner)
        payload = {
            "start_date": str(start),
            "end_date": str(start + timedelta(days=2)),
            "available_units": 2,
            "custom_price": "999",
        }
        response = self.client.post(f"/api/rooms/{self.room.id}/availability/bulk/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["updated"], 3)

    def test_lifecycle(self):
        draft = Stay.objects.create(
            owner=self.owner,
            name="Draft",
            description="complete " * 20,
            stay_type=StayType.HOTEL,
            region="Manzini",
            town="Manzini",
            location={"latitude": -26.5, "longitude": 31.4},
        )
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f"/api/stays/{draft.id}/submit/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/stays/{self.stay.id}/pause/").status_code, 200)

    def test_manager_mine_returns_manageable_stays_with_quality(self):
        draft = Stay.objects.create(owner=self.owner, name="Draft Stay", stay_type=StayType.HOTEL)
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/stays/mine/")
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(str(self.stay.id), ids)
        self.assertIn(str(draft.id), ids)
        self.assertIn("quality", response.data["results"][0])
