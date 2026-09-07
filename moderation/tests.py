from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from properties.models import ListingStatus, ListingType, PropertyListing, PropertyType
from .models import ListingReport, ModerationAuditEvent


def user(email, staff=False):
    return get_user_model().objects.create_user(
        email=email, password="test-pass-123", first_name="Test", last_name="User", is_staff=staff
    )


class ModerationApiTests(APITestCase):
    def setUp(self):
        self.owner = user("listing-owner@example.com")
        self.reporter = user("reporter@example.com")
        self.admin = user("admin@example.com", True)
        self.property = PropertyListing.objects.create(
            owner=self.owner,
            title="Reported home",
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=5000,
            status=ListingStatus.DRAFT,
        )

    def test_report_requires_exactly_one_target_and_blocks_duplicate(self):
        self.client.force_authenticate(self.reporter)
        self.assertEqual(self.client.post("/api/reports/listings/", {"reason": "SCAM"}, format="json").status_code, 400)
        payload = {"property": str(self.property.id), "reason": "SCAM", "details": "Suspicious"}
        self.assertEqual(self.client.post("/api/reports/listings/", payload, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/reports/listings/", payload, format="json").status_code, 400)

    def test_database_rejects_report_without_target(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ListingReport.objects.create(reporter=self.reporter, reason="OTHER")

    def test_admin_suspension_requires_reason_and_is_audited(self):
        self.client.force_authenticate(self.admin)
        url = f"/api/moderation/listings/property/{self.property.id}/suspend/"
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"reason": "Fraud investigation"}, format="json").status_code, 200)
        self.property.refresh_from_db()
        self.assertEqual(self.property.status, ListingStatus.SUSPENDED)
        self.assertTrue(ModerationAuditEvent.objects.filter(property=self.property, action="LISTING_SUSPEND").exists())

    def test_non_admin_cannot_moderate_or_read_summary(self):
        self.client.force_authenticate(self.reporter)
        self.assertEqual(self.client.get("/api/moderation/summary/").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/api/moderation/listings/property/{self.property.id}/suspend/", {"reason": "No"}, format="json"
            ).status_code,
            403,
        )
