from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import User
from favourites.models import Favourite
from properties.models import (
    AvailabilityStatus,
    ListingStatus,
    ListingType,
    PropertyImage,
    PropertyListing,
    PropertyType,
)
from stays.models import RoomType, Stay, StayImage, StayStatus, StayType


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    FEATURED_LISTINGS_CACHE_SECONDS=60,
    PUBLIC_CONFIG_CACHE_SECONDS=900,
    PUBLIC_REFERENCE_CACHE_SECONDS=3600,
)
class PublicPerformanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="perf-owner@example.com",
            password="StrongPass123!",
            first_name="Perf",
            last_name="Owner",
        )
        self.seeker = User.objects.create_user(
            email="perf-seeker@example.com",
            password="StrongPass123!",
            first_name="Perf",
            last_name="Seeker",
        )

    def test_config_and_reference_are_publicly_cacheable(self):
        config = self.client.get("/api/v1/config/")
        reference = self.client.get("/api/v1/reference/")

        self.assertEqual(config.status_code, 200)
        self.assertEqual(reference.status_code, 200)
        self.assertEqual(config["Cache-Control"], "public, max-age=900")
        self.assertEqual(reference["Cache-Control"], "public, max-age=3600")

        with CaptureQueriesContext(connection) as config_queries:
            self.client.get("/api/v1/config/")
        with CaptureQueriesContext(connection) as reference_queries:
            self.client.get("/api/v1/reference/")

        self.assertEqual(len(config_queries), 0)
        self.assertEqual(len(reference_queries), 0)

    def test_featured_property_cards_do_not_load_full_galleries(self):
        for index in range(6):
            listing = PropertyListing.objects.create(
                owner=self.owner,
                title=f"Featured House {index}",
                description="A featured property listing. " * 4,
                listing_type=ListingType.RENT,
                property_type=PropertyType.HOUSE,
                price="12000.00",
                region="Hhohho",
                town="Ezulwini",
                location={"latitude": -26.4, "longitude": 31.2},
                status=ListingStatus.PUBLISHED,
                availability_status=AvailabilityStatus.AVAILABLE,
                featured=True,
            )
            for image_index in range(4):
                PropertyImage.objects.create(
                    property=listing,
                    image=f"properties/{index}-{image_index}.jpg",
                    sort_order=image_index,
                    is_cover=image_index == 0,
                )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/properties/featured/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
        self.assertEqual(len(response.json()["results"]), 6)
        self.assertLessEqual(len(queries), 4)

    def test_featured_stay_cards_use_aggregates_instead_of_room_n_plus_one(self):
        for index in range(6):
            stay = Stay.objects.create(
                owner=self.owner,
                name=f"Featured Stay {index}",
                description="A featured stay. " * 6,
                stay_type=StayType.LODGE,
                region="Hhohho",
                town="Mbabane",
                location={"latitude": -26.3, "longitude": 31.1},
                status=StayStatus.PUBLISHED,
                featured=True,
            )
            StayImage.objects.create(stay=stay, image=f"stays/{index}.jpg", is_cover=True)
            for room_index in range(3):
                RoomType.objects.create(
                    stay=stay,
                    name=f"Room {room_index}",
                    capacity_adults=2,
                    total_capacity=2,
                    quantity=2,
                    base_price=str(800 + room_index),
                    is_active=True,
                )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/stays/featured/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=60")
        self.assertEqual(len(response.json()["results"]), 6)
        self.assertLessEqual(len(queries), 4)

    def test_authenticated_featured_response_is_not_publicly_cached(self):
        listing = PropertyListing.objects.create(
            owner=self.owner,
            title="Saved Featured House",
            description="A featured property listing. " * 4,
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price="12000.00",
            region="Hhohho",
            town="Ezulwini",
            location={"latitude": -26.4, "longitude": 31.2},
            status=ListingStatus.PUBLISHED,
            availability_status=AvailabilityStatus.AVAILABLE,
            featured=True,
        )
        Favourite.objects.create(user=self.seeker, property=listing)
        self.client.force_authenticate(self.seeker)

        response = self.client.get("/api/v1/properties/featured/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.json()["results"][0]["is_favourited"])
