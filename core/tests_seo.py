from django.test import TestCase, override_settings

from accounts.models import User
from properties.models import ListingStatus, ListingType, PropertyListing, PropertyType
from stays.models import Stay, StayStatus, StayType


@override_settings(FRONTEND_BASE_URL="https://sureplace.twinpeaksinvestment.com")
class SitemapTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="seo-owner@example.com",
            password="StrongPass123!",
            first_name="Seo",
            last_name="Owner",
        )

    def test_sitemap_includes_public_routes_and_published_listings(self):
        published = PropertyListing.objects.create(
            owner=self.owner,
            title="Published Ezulwini House",
            description="A published property listing. " * 4,
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price="12000.00",
            region="Hhohho",
            town="Ezulwini",
            location={"latitude": -26.4, "longitude": 31.2},
            status=ListingStatus.PUBLISHED,
        )
        draft = PropertyListing.objects.create(
            owner=self.owner,
            title="Draft Ezulwini House",
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price="12000.00",
            status=ListingStatus.DRAFT,
        )
        stay = Stay.objects.create(
            owner=self.owner,
            name="Published Mountain Stay",
            description="A published stay. " * 6,
            stay_type=StayType.LODGE,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.3, "longitude": 31.1},
            status=StayStatus.PUBLISHED,
        )

        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        body = response.content.decode()
        self.assertIn("<loc>https://sureplace.twinpeaksinvestment.com/</loc>", body)
        self.assertIn("<loc>https://sureplace.twinpeaksinvestment.com/properties</loc>", body)
        self.assertIn("<loc>https://sureplace.twinpeaksinvestment.com/stays</loc>", body)
        self.assertIn(
            f"<loc>https://sureplace.twinpeaksinvestment.com/properties/{published.slug}</loc>",
            body,
        )
        self.assertIn(f"<loc>https://sureplace.twinpeaksinvestment.com/stays/{stay.slug}</loc>", body)
        self.assertNotIn(draft.slug, body)

    @override_settings(FEATURE_FLAGS={"properties": True, "stays": False})
    def test_sitemap_excludes_stays_when_feature_is_disabled(self):
        response = self.client.get("/sitemap.xml")

        body = response.content.decode()
        self.assertNotIn("<loc>https://sureplace.twinpeaksinvestment.com/stays</loc>", body)
