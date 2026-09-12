from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from properties.models import ListingStatus, ListingType, PropertyListing, PropertyType
from notifications.models import Notification
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


class StaffPropertyModerationApiTests(APITestCase):
    def setUp(self):
        self.owner = user("owner@example.com")
        self.owner.is_email_verified = True
        self.owner.save(update_fields=["is_email_verified"])
        self.staff = user("reviewer@example.com", True)
        self.submitted = PropertyListing.objects.create(
            owner=self.owner,
            title="Submitted family home",
            description="A complete listing ready for staff review. " * 4,
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=6500,
            region="Hhohho",
            town="Mbabane",
            location={"latitude": -26.305, "longitude": 31.136},
            status=ListingStatus.SUBMITTED,
        )
        self.published = PropertyListing.objects.create(
            owner=self.owner,
            title="Published family home",
            description="A complete listing already live on SurePlace. " * 4,
            listing_type=ListingType.SALE,
            property_type=PropertyType.HOUSE,
            price=850000,
            region="Manzini",
            town="Manzini",
            location={"latitude": -26.499, "longitude": 31.38},
            status=ListingStatus.PUBLISHED,
        )
        content_type = ContentType.objects.get_for_model(PropertyListing)
        permissions = Permission.objects.filter(
            content_type=content_type,
            codename__in=[
                "review_propertylisting",
                "approve_propertylisting",
                "request_changes_propertylisting",
                "suspend_propertylisting",
                "restore_propertylisting",
                "add_note_propertylisting",
            ],
        )
        self.staff.user_permissions.set(permissions)

    def test_staff_property_queue_requires_staff_permission(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get("/api/staff/properties/").status_code, 403)

        unpermitted_staff = user("limited@example.com", True)
        self.client.force_authenticate(unpermitted_staff)
        self.assertEqual(self.client.get("/api/staff/properties/").status_code, 403)

        self.client.force_authenticate(self.staff)
        response = self.client.get("/api/staff/properties/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(str(self.submitted.id), [item["id"] for item in response.data["results"]])

    def test_staff_summary_uses_real_listing_counts(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get("/api/staff/properties/summary/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["awaiting_review"], 1)
        self.assertEqual(response.data["suspended"], 0)

    def test_staff_approve_publishes_and_audits_listing(self):
        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/staff/properties/{self.submitted.id}/approve/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, ListingStatus.PUBLISHED)
        self.assertIsNotNone(self.submitted.published_at)
        self.assertTrue(
            ModerationAuditEvent.objects.filter(property=self.submitted, action="PROPERTY_APPROVED").exists()
        )
        notification = Notification.objects.get(user=self.owner, data__action="PROPERTY_APPROVED")
        self.assertEqual(notification.data["route"], f"/properties/{self.submitted.slug}")
        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/notifications/{notification.id}/").data
        self.assertEqual(detail["action"], {"label": "View listing", "url": f"/properties/{self.submitted.slug}"})

    def test_staff_can_request_changes_and_owner_can_resubmit(self):
        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/staff/properties/{self.submitted.id}/request-changes/",
                {"reason": "Please add clearer photos."},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, ListingStatus.CHANGES_REQUESTED)
        self.assertTrue(
            ModerationAuditEvent.objects.filter(
                property=self.submitted, action="PROPERTY_CHANGES_REQUESTED", reason__icontains="clearer photos"
            ).exists()
        )
        notification = Notification.objects.get(user=self.owner, data__action="PROPERTY_CHANGES_REQUESTED")
        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/notifications/{notification.id}/").data
        self.assertEqual(
            detail["action"],
            {"label": "Review changes", "url": f"/account/manage/properties/{self.submitted.id}/edit"},
        )

        self.client.force_authenticate(self.owner)
        resubmit = self.client.post(f"/api/properties/{self.submitted.id}/submit/")
        self.assertEqual(resubmit.status_code, 200, resubmit.data)
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, ListingStatus.SUBMITTED)

    def test_staff_can_suspend_and_restore_published_listing(self):
        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            suspend = self.client.post(
                f"/api/staff/properties/{self.published.id}/suspend/",
                {"reason": "Owner verification concern."},
                format="json",
            )
        self.assertEqual(suspend.status_code, 200, suspend.data)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, ListingStatus.SUSPENDED)
        notification = Notification.objects.get(user=self.owner, data__action="PROPERTY_SUSPENDED")
        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/notifications/{notification.id}/").data
        self.assertEqual(detail["action"]["url"], f"/account/manage/properties/{self.published.id}/edit")

        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            restore = self.client.post(f"/api/staff/properties/{self.published.id}/restore/", {}, format="json")
        self.assertEqual(restore.status_code, 200, restore.data)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, ListingStatus.PUBLISHED)
        notification = Notification.objects.get(user=self.owner, data__action="PROPERTY_RESTORED")
        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/notifications/{notification.id}/").data
        self.assertEqual(detail["action"], {"label": "View listing", "url": f"/properties/{self.published.slug}"})
