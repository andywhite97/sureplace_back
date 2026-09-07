from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.test import TestCase, skipUnlessDBFeature
from accounts.models import User
from properties.models import ListingType, PropertyListing, PropertyType


class PostGISTests(TestCase):
    @skipUnlessDBFeature("gis_enabled")
    def test_geometry_round_trip_and_bounds(self):
        user = User.objects.create_user(
            email="geo@example.com", password="StrongPass123!", first_name="Geo", last_name="Test"
        )
        listing = PropertyListing.objects.create(
            owner=user,
            title="Geo home",
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=1000,
            location=Point(31.13, -26.32, srid=4326),
        )
        listing.refresh_from_db()
        self.assertAlmostEqual(listing.location.x, 31.13)
        bounds = Polygon.from_bbox((31.0, -26.5, 31.3, -26.1))
        self.assertTrue(PropertyListing.objects.filter(location__within=bounds).exists())
        with connection.cursor() as cursor:
            cursor.execute("SELECT PostGIS_Version()")
            self.assertTrue(cursor.fetchone()[0])
