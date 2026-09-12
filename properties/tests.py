import shutil
import tempfile
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from agencies.models import Agency, AgentProfile
from .models import (
    Amenity,
    AvailabilityStatus,
    ListingStatus,
    ListingType,
    PropertyImage,
    PropertyListing,
    PropertyType,
)
from .services import listing_quality


def listing_data(**overrides):
    data = {
        "title": "Modern House in Ezulwini",
        "description": "A spacious family home with mountain views. " * 4,
        "listing_type": ListingType.RENT,
        "property_type": PropertyType.HOUSE,
        "price": "12500.00",
        "region": "Hhohho",
        "town": "Ezulwini",
        "suburb": "Lobamba",
        "latitude": -26.399,
        "longitude": 31.176,
        "bedrooms": 3,
        "bathrooms": 2,
        "parking_spaces": 2,
    }
    data.update(overrides)
    return data


def make_listing(owner, **overrides):
    data = listing_data(**overrides)
    latitude = data.pop("latitude")
    longitude = data.pop("longitude")
    data["location"] = {"latitude": latitude, "longitude": longitude}
    return PropertyListing.objects.create(owner=owner, **data)


def image_file(name="photo.png"):
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(0, 128, 128)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class PropertyModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="StrongPass123!", first_name="Owner", last_name="One"
        )

    def test_slug_and_public_id_are_unique(self):
        first = make_listing(self.user)
        second = make_listing(self.user)
        self.assertNotEqual(first.slug, second.slug)
        self.assertNotEqual(first.public_id, second.public_id)
        self.assertTrue(first.public_id.startswith("SP-"))

    def test_negative_values_are_rejected(self):
        for field in ("price", "bedrooms", "bathrooms", "parking_spaces", "floor_area", "land_area"):
            listing = make_listing(self.user)
            setattr(listing, field, -1)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                listing.full_clean()

    def test_land_rejects_room_counts_but_does_not_require_them(self):
        land = make_listing(self.user, property_type=PropertyType.LAND, bedrooms=None, bathrooms=None)
        land.full_clean()
        land.bedrooms = 2
        with self.assertRaises(ValidationError):
            land.full_clean()

    def test_images_are_ordered_and_only_one_cover_remains(self):
        listing = make_listing(self.user)
        later = PropertyImage.objects.create(
            property=listing, image="properties/later.jpg", sort_order=2, is_cover=True
        )
        first = PropertyImage.objects.create(
            property=listing, image="properties/first.jpg", sort_order=1, is_cover=True
        )
        later.refresh_from_db()
        self.assertFalse(later.is_cover)
        self.assertTrue(first.is_cover)
        self.assertEqual(list(listing.images.values_list("sort_order", flat=True)), [1, 2])
        self.assertEqual(listing.cover_image, first)

    def test_amenities_and_quality_score(self):
        listing = make_listing(self.user)
        amenities = list(Amenity.objects.all()[:3])
        listing.amenities.set(amenities)
        low = listing_quality(listing)
        for number in range(5):
            PropertyImage.objects.create(property=listing, image=f"properties/{number}.jpg", sort_order=number)
        listing.availability_confirmed_at = listing.created_at
        listing.save()
        high = listing_quality(listing)
        self.assertEqual(listing.amenities.count(), 3)
        self.assertGreater(high["score"], low["score"])
        self.assertNotIn("Add at least 5 photos", high["suggestions"])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PropertyAPITests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings["MEDIA_ROOT"]
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Owner",
            last_name="One",
            is_email_verified=True,
        )
        self.other = User.objects.create_user(
            email="other@example.com",
            password="StrongPass123!",
            first_name="Other",
            last_name="User",
            is_email_verified=True,
        )
        self.published = make_listing(
            self.owner,
            status=ListingStatus.PUBLISHED,
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        self.draft = make_listing(self.owner, title="Private Draft", status=ListingStatus.DRAFT, price="5000")
        self.client = APIClient()

    def test_anonymous_list_and_detail_access(self):
        listing_response = self.client.get("/api/properties/")
        detail_response = self.client.get(f"/api/properties/{self.published.slug}/")
        self.assertEqual(listing_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["latitude"], -26.399)
        self.assertEqual(detail_response.data["longitude"], 31.176)
        self.assertNotIn("quality", detail_response.data)
        self.assertNotIn("owner", detail_response.data)

    def test_public_list_only_contains_published(self):
        response = self.client.get("/api/properties/")
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(str(self.published.id), ids)
        self.assertNotIn(str(self.draft.id), ids)

    def test_authenticated_user_can_create_draft(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post("/api/properties/", listing_data(title="New Draft"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        listing = PropertyListing.objects.get(id=response.data["id"])
        self.assertEqual(listing.owner, self.owner)
        self.assertEqual(listing.status, ListingStatus.DRAFT)

    def test_anonymous_user_cannot_create(self):
        response = self.client.post("/api/properties/", listing_data(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_negative_price_and_counts(self):
        self.client.force_authenticate(self.owner)
        for field in ("price", "bedrooms", "bathrooms", "parking_spaces"):
            response = self.client.post("/api/properties/", listing_data(**{field: -1}), format="json")
            with self.subTest(field=field):
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_edit_by_uuid_and_non_owner_cannot(self):
        url = f"/api/properties/{self.draft.id}/"
        self.client.force_authenticate(self.owner)
        allowed = self.client.patch(url, {"title": "Updated"}, format="json")
        self.assertEqual(allowed.status_code, status.HTTP_200_OK, allowed.data)
        self.client.force_authenticate(self.other)
        denied = self.client.patch(url, {"title": "Hijacked"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_assigned_agent_and_agency_staff_can_manage(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        agent = AgentProfile.objects.create(user=self.other, agency=agency)
        listing = make_listing(self.owner, agency=agency, agent=agent)
        colleague = User.objects.create_user(
            email="staff@example.com",
            password="StrongPass123!",
            first_name="Staff",
            last_name="Member",
            is_email_verified=True,
        )
        AgentProfile.objects.create(user=colleague, agency=agency)
        for user in (self.other, colleague):
            self.client.force_authenticate(user)
            response = self.client.patch(f"/api/properties/{listing.slug}/", {"suburb": "Changed"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_filters_search_and_ordering(self):
        sale = make_listing(
            self.owner,
            title="Affordable Office Manzini",
            listing_type=ListingType.SALE,
            property_type=PropertyType.OFFICE,
            price="900000",
            bedrooms=4,
            town="Manzini",
            suburb="Central",
            status=ListingStatus.PUBLISHED,
        )
        cases = (
            ({"listing_type": "SALE"}, sale),
            ({"property_type": "OFFICE"}, sale),
            ({"min_price": "800000", "max_price": "950000"}, sale),
            ({"min_bedrooms": "4"}, sale),
            ({"town": "manzini"}, sale),
            ({"search": "Affordable"}, sale),
        )
        for query, expected in cases:
            response = self.client.get("/api/properties/", query)
            with self.subTest(query=query):
                self.assertEqual([item["id"] for item in response.data["results"]], [str(expected.id)])
        ascending = self.client.get("/api/properties/", {"ordering": "price_asc"})
        self.assertEqual(ascending.data["results"][0]["id"], str(self.published.id))

    def test_map_bounds_filter(self):
        response = self.client.get("/api/properties/", {"north": -26, "south": -27, "east": 32, "west": 31})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(self.published.id), [item["id"] for item in response.data["results"]])

    def test_featured_endpoint_only_returns_available_featured(self):
        self.published.featured = True
        self.published.save()
        make_listing(
            self.owner,
            title="Unavailable Feature",
            status=ListingStatus.PUBLISHED,
            featured=True,
            availability_status=AvailabilityStatus.UNAVAILABLE,
        )
        response = self.client.get("/api/properties/featured/")
        self.assertEqual([item["id"] for item in response.data["results"]], [str(self.published.id)])

    def test_submit_pause_and_confirm_availability_workflows(self):
        self.client.force_authenticate(self.owner)
        submit = self.client.post(f"/api/properties/{self.draft.id}/submit/")
        self.assertEqual(submit.status_code, status.HTTP_200_OK, submit.data)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ListingStatus.SUBMITTED)

        pause = self.client.post(f"/api/properties/{self.published.id}/pause/")
        self.assertEqual(pause.status_code, status.HTTP_200_OK)
        confirm = self.client.post(f"/api/properties/{self.published.id}/confirm-availability/")
        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, ListingStatus.PAUSED)
        self.assertEqual(self.published.availability_status, AvailabilityStatus.AVAILABLE)
        self.assertIsNotNone(self.published.availability_confirmed_at)

    def test_owner_detail_includes_quality(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/api/properties/{self.published.slug}/")
        self.assertIn("score", response.data["quality"])
        self.assertIn("suggestions", response.data["quality"])

    def test_manager_mine_returns_drafts_and_quality(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/properties/mine/")
        ids = [item["id"] for item in response.data["results"]]
        self.assertIn(str(self.published.id), ids)
        self.assertIn(str(self.draft.id), ids)
        self.assertIn("quality", response.data["results"][0])

    def test_multiple_image_uploads_keep_first_default_cover(self):
        self.client.force_authenticate(self.owner)

        first = self.client.post(
            f"/api/properties/{self.draft.id}/images/",
            {"image": image_file("first.png"), "sort_order": 0},
            format="multipart",
        )
        second = self.client.post(
            f"/api/properties/{self.draft.id}/images/",
            {"image": image_file("second.png"), "sort_order": 1, "is_cover": "true"},
            format="multipart",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        images = list(self.draft.images.order_by("sort_order", "created_at"))
        self.assertEqual(len(images), 2)
        self.assertEqual([image.sort_order for image in images], [0, 1])
        self.assertTrue(images[0].is_cover)
        self.assertFalse(images[1].is_cover)
        self.assertEqual(self.draft.images.filter(is_cover=True).count(), 1)
        self.assertTrue(images[0].image.name)

    def test_set_cover_preserves_order_and_keeps_one_cover(self):
        self.client.force_authenticate(self.owner)
        first = PropertyImage.objects.create(property=self.draft, image="properties/first.jpg", sort_order=0)
        second = PropertyImage.objects.create(property=self.draft, image="properties/second.jpg", sort_order=1)
        PropertyImage.objects.filter(pk=first.pk).update(is_cover=True)

        response = self.client.patch(
            f"/api/properties/{self.draft.id}/images/",
            {"id": str(second.id), "is_cover": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.sort_order, 0)
        self.assertFalse(first.is_cover)
        self.assertEqual(second.sort_order, 1)
        self.assertTrue(second.is_cover)
        self.assertEqual(self.draft.images.filter(is_cover=True).count(), 1)

    def test_reorder_preserves_cover_and_deleting_cover_promotes_first_remaining(self):
        self.client.force_authenticate(self.owner)
        first = PropertyImage.objects.create(property=self.draft, image="properties/first.jpg", sort_order=0)
        second = PropertyImage.objects.create(property=self.draft, image="properties/second.jpg", sort_order=1)
        third = PropertyImage.objects.create(property=self.draft, image="properties/third.jpg", sort_order=2)
        PropertyImage.objects.filter(pk=second.pk).update(is_cover=True)

        reorder = self.client.patch(
            f"/api/properties/{self.draft.id}/images/",
            {"id": str(third.id), "sort_order": 0},
            format="json",
        )
        self.assertEqual(reorder.status_code, status.HTTP_200_OK, reorder.data)
        third.refresh_from_db()
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(third.sort_order, 0)
        self.assertFalse(third.is_cover)
        self.assertEqual(first.sort_order, 1)
        self.assertFalse(first.is_cover)
        self.assertEqual(second.sort_order, 2)
        self.assertTrue(second.is_cover)

        delete = self.client.delete(f"/api/properties/{self.draft.id}/images/?id={second.id}")
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)
        third.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(third.sort_order, 0)
        self.assertTrue(third.is_cover)
        self.assertEqual(first.sort_order, 1)
        self.assertFalse(first.is_cover)

    def test_non_manager_cannot_upload_listing_image(self):
        image = PropertyImage.objects.create(property=self.draft, image="properties/cover.jpg", sort_order=0)
        self.client.force_authenticate(self.other)
        response = self.client.post(
            f"/api/properties/{self.draft.id}/images/",
            {"image": image_file(), "sort_order": 0},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        set_cover = self.client.patch(
            f"/api/properties/{self.draft.id}/images/",
            {"id": str(image.id), "is_cover": True},
            format="json",
        )
        self.assertEqual(set_cover.status_code, status.HTTP_403_FORBIDDEN)
