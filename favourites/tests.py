from rest_framework.test import APITestCase
from accounts.models import User
from properties.models import PropertyListing, ListingStatus
from stays.models import Stay, StayStatus, StayType
from .models import Favourite


class FavouriteTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="fav@example.com", password="StrongPass123!", first_name="F", last_name="U"
        )
        self.other = User.objects.create_user(
            email="fav2@example.com", password="StrongPass123!", first_name="O", last_name="U"
        )
        self.property = PropertyListing.objects.create(
            owner=self.user,
            title="Home",
            description="Desc",
            listing_type="RENT",
            property_type="HOUSE",
            price=10,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=ListingStatus.PUBLISHED,
        )
        self.stay = Stay.objects.create(
            owner=self.user,
            name="Lodge",
            description="Desc",
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
        )

    def test_auth_add_cards_duplicate_filter_remove(self):
        self.assertEqual(
            self.client.post("/api/favourites/", {"property": str(self.property.id)}, format="json").status_code, 401
        )
        self.client.force_authenticate(self.user)
        a = self.client.post("/api/favourites/", {"property": str(self.property.id)}, format="json")
        b = self.client.post("/api/favourites/", {"stay": str(self.stay.id)}, format="json")
        self.assertEqual((a.status_code, b.status_code), (201, 201))
        self.assertEqual(
            self.client.post("/api/favourites/", {"property": str(self.property.id)}, format="json").status_code, 400
        )
        data = self.client.get("/api/favourites/").data["results"]
        self.assertTrue(any(x["property_card"] for x in data))
        self.assertTrue(any(x["stay_card"] for x in data))
        self.assertEqual(self.client.get("/api/favourites/", {"type": "property"}).data["count"], 1)
        self.assertEqual(self.client.delete(f"/api/favourites/{a.data['id']}/").status_code, 204)

    def test_exactly_one_isolation_and_cascade(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post("/api/favourites/", {}, format="json").status_code, 400)
        fav = Favourite.objects.create(user=self.other, property=self.property)
        self.assertEqual(self.client.get(f"/api/favourites/{fav.id}/").status_code, 404)
        self.property.delete()
        self.assertFalse(Favourite.objects.filter(id=fav.id).exists())

    def test_favourite_state(self):
        Favourite.objects.create(user=self.user, property=self.property)
        self.assertFalse(self.client.get("/api/properties/").data["results"][0]["is_favourited"])
        self.client.force_authenticate(self.user)
        self.assertTrue(self.client.get("/api/properties/").data["results"][0]["is_favourited"])
