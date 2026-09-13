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


class StaffDashboardApiTests(APITestCase):
    def setUp(self):
        StaffPropertyModerationApiTests.setUp(self)

    def test_summary_dashboard_is_staff_and_permission_protected(self):
        self.assertIn(self.client.get("/api/v1/staff/properties/summary/").status_code, [401, 403])
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get("/api/v1/staff/properties/summary/").status_code, 403)
        self.client.force_authenticate(user("no-permission@example.com", True))
        self.assertEqual(self.client.get("/api/v1/staff/properties/summary/").status_code, 403)

    def test_dashboard_counts_queue_activity_and_private_fields(self):
        from datetime import timedelta
        from django.utils import timezone
        from properties.models import PropertyImage
        from verification.models import VerificationRequest, RequestStatus, VerificationType

        self.staff.user_permissions.add(Permission.objects.get(codename="review_verificationrequest"))
        self.client.force_authenticate(self.staff)
        VerificationRequest.objects.create(
            applicant=self.owner, verification_type=VerificationType.AGENCY, status=RequestStatus.SUBMITTED
        )
        VerificationRequest.objects.create(
            applicant=self.owner, verification_type=VerificationType.IDENTITY, status=RequestStatus.UNDER_REVIEW
        )
        VerificationRequest.objects.create(
            applicant=self.owner, verification_type=VerificationType.IDENTITY, status=RequestStatus.DRAFT
        )
        ListingReport.objects.create(reporter=self.owner, property=self.submitted, reason="OTHER")
        PropertyImage.objects.create(property=self.submitted, image="test-cover.jpg", is_cover=True)
        PropertyImage.objects.create(property=self.submitted, image="test-other.jpg")
        now = timezone.now()
        for index in range(8):
            listing = PropertyListing.objects.create(
                owner=self.owner,
                title=f"Queue {index}",
                listing_type=ListingType.RENT,
                property_type=PropertyType.HOUSE,
                price=5000,
                status=ListingStatus.SUBMITTED,
            )
            PropertyListing.objects.filter(pk=listing.pk).update(updated_at=now - timedelta(hours=index + 1))
            event = ModerationAuditEvent.objects.create(
                actor=self.staff,
                property=listing,
                action="PROPERTY_APPROVED",
                reason="private audit note",
                metadata={"private": "secret"},
            )
            ModerationAuditEvent.objects.filter(pk=event.pk).update(created_at=now - timedelta(minutes=index))
        response = self.client.get("/api/v1/staff/properties/summary/")
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["awaiting_review"], 9)
        self.assertEqual(data["open_reports"], 1)
        self.assertEqual(data["agency_reviews"], 1)
        self.assertEqual(data["verification_requests"], 2)
        self.assertEqual(len(data["latest_listings"]), 5)
        self.assertEqual(data["latest_listings"][0]["id"], str(self.submitted.id))
        self.assertEqual(data["latest_listings"][0]["image_count"], 2)
        self.assertIn("test-cover.jpg", data["latest_listings"][0]["cover_image"])
        self.assertEqual(data["latest_listings"][0]["open_reports_count"], 1)
        self.assertEqual(len(data["recent_activity"]), 7)
        dates = [row["created_at"] for row in data["recent_activity"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        for row in data["latest_listings"]:
            for field in ["owner", "description", "images", "latest_note", "reports"]:
                self.assertNotIn(field, row)
        for row in data["recent_activity"]:
            for field in ["actor_email", "reason", "metadata"]:
                self.assertNotIn(field, row)
        self.assertNotIn("private audit note", str(data))
        self.assertNotIn(self.owner.email, str(data))

    def test_unavailable_verification_counts_are_not_fabricated_zeroes(self):
        self.client.force_authenticate(self.staff)
        data = self.client.get("/api/v1/staff/properties/summary/").data
        self.assertIsNone(data["agency_reviews"])
        self.assertIsNone(data["verification_requests"])

    def test_dashboard_query_count_does_not_grow_per_queue_row(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_authenticate(self.staff)
        # Warm Django's user permission cache before comparing row counts.
        self.client.get("/api/v1/staff/properties/summary/")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/api/v1/staff/properties/summary/")
        for index in range(6):
            PropertyListing.objects.create(
                owner=self.owner,
                title=f"Extra {index}",
                listing_type=ListingType.RENT,
                property_type=PropertyType.HOUSE,
                price=5000,
                status=ListingStatus.SUBMITTED,
            )
        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/api/v1/staff/properties/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 8)
