from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from rest_framework.test import APITestCase
from accounts.models import User
from stays.models import Stay, StayStatus, RoomType
from stays.services import submit
from notifications.models import Notification
from .models import ModerationAuditEvent


class StaffStayTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="stay-owner@example.com", password="test-password", first_name="Stay", last_name="Owner")
        self.staff = User.objects.create_user(email="stay-reviewer@example.com", password="test-password", is_staff=True, first_name="Stay", last_name="Reviewer")
        self.staff.user_permissions.set(Permission.objects.filter(content_type=ContentType.objects.get_for_model(Stay)))
        location = {"latitude": -26.3, "longitude": 31.1}
        if not settings.USE_SQLITE:
            from django.contrib.gis.geos import Point
            location = Point(31.1, -26.3, srid=4326)
        self.stay = Stay.objects.create(owner=self.owner, name="Review lodge", description="A complete stay",
            stay_type="LODGE", region="Hhohho", town="Mbabane", location=location, status=StayStatus.SUBMITTED)
        RoomType.objects.create(stay=self.stay, name="Standard room", capacity_adults=2, total_capacity=2, quantity=1, base_price=500)
        self.client.force_authenticate(self.staff)

    def post(self, action, data=None):
        return self.client.post(f"/api/v1/staff/stays/{self.stay.id}/{action}/", data or {}, format="json")

    def test_permissions_separate_review_from_approval(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get("/api/v1/staff/stays/").status_code, 403)
        self.client.force_authenticate(self.staff)
        self.staff.user_permissions.set(Permission.objects.filter(codename="review_stay"))
        self.assertEqual(self.client.get("/api/v1/staff/stays/").status_code, 200)
        self.assertEqual(self.post("approve").status_code, 403)

    def test_review_approve_audit_and_owner_notification(self):
        self.assertEqual(self.client.get("/api/v1/staff/stays/summary/").data["awaiting_review"], 1)
        self.assertEqual(self.post("start-review").data["status"], StayStatus.UNDER_REVIEW)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("approve")
        self.assertEqual(response.status_code, 200, response.data)
        self.stay.refresh_from_db()
        self.assertEqual(self.stay.status, StayStatus.PUBLISHED)
        self.assertIsNotNone(self.stay.published_at)
        self.assertTrue(ModerationAuditEvent.objects.filter(stay=self.stay, action="STAY_APPROVED").exists())
        self.assertEqual(Notification.objects.get(user=self.owner).data["route"], f"/stays/{self.stay.slug}")
        self.assertEqual(self.post("approve").status_code, 400)

    def test_changes_require_feedback_and_allow_host_resubmission(self):
        self.assertEqual(self.post("request-changes").status_code, 400)
        self.assertEqual(self.post("request-changes", {"reason": "Correct the room information"}).status_code, 200)
        self.stay.refresh_from_db()
        self.assertEqual(self.stay.status, StayStatus.CHANGES_REQUESTED)
        submit(self.stay)
        self.assertEqual(self.stay.status, StayStatus.SUBMITTED)

    def test_invalid_stay_cannot_be_published(self):
        self.stay.room_types.all().delete()
        self.assertEqual(self.post("approve").status_code, 400)
        self.stay.refresh_from_db()
        self.assertEqual(self.stay.status, StayStatus.SUBMITTED)
        self.assertFalse(ModerationAuditEvent.objects.filter(stay=self.stay).exists())

    def test_legacy_reinstate_cannot_bypass_approval(self):
        response = self.client.post(f"/api/v1/moderation/listings/stay/{self.stay.id}/reinstate/", {}, format="json")
        self.assertEqual(response.status_code, 400)
        suspend = self.client.post(f"/api/v1/moderation/listings/stay/{self.stay.id}/suspend/", {"reason": "Review"}, format="json")
        self.assertEqual(suspend.status_code, 400)
        self.stay.refresh_from_db()
        self.assertEqual(self.stay.status, StayStatus.SUBMITTED)

    def test_verification_evidence_links_require_verification_review_permission(self):
        from verification.models import VerificationRequest, VerificationDocument
        request = VerificationRequest.objects.create(applicant=self.owner, stay=self.stay, verification_type="STAY", status="SUBMITTED")
        VerificationDocument.objects.create(verification_request=request, document_type="BUSINESS_REGISTRATION", file="evidence-test.pdf")
        url = f"/api/v1/staff/stays/{self.stay.id}/"
        self.assertEqual(self.client.get(url).data["verification_requests"], [])
        self.assertIsNone(self.client.get(url).data["verification_document_count"])
        self.staff.user_permissions.add(Permission.objects.get(codename="review_verificationrequest"))
        if hasattr(self.staff, "_perm_cache"):
            del self.staff._perm_cache
        if hasattr(self.staff, "_user_perm_cache"):
            del self.staff._user_perm_cache
        response = self.client.get(url)
        self.assertEqual(str(response.data["verification_requests"][0]["id"]), str(request.id))
        self.assertEqual(response.data["verification_request_count"], 1)
        self.assertEqual(response.data["verification_document_count"], 1)

    def test_dashboard_counts_are_global_and_filters_use_real_fields(self):
        Stay.objects.create(owner=self.owner, name="Other lodge", stay_type="LODGE", town="Manzini", status=StayStatus.UNDER_REVIEW)
        Stay.objects.create(owner=self.owner, name="Rejected lodge", stay_type="LODGE", town="Siteki", status=StayStatus.REJECTED)
        summary = self.client.get("/api/v1/staff/stays/summary/").data
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["submitted"], 1)
        self.assertEqual(summary["under_review"], 1)
        self.assertEqual(summary["rejected"], 1)
        self.assertIn("Manzini", summary["towns"])
        self.assertEqual(summary["hosts"][0]["id"], str(self.owner.id))
        response = self.client.get("/api/v1/staff/stays/", {"town": "Mbabane", "host": str(self.owner.id), "ordering": "name", "page_size": 1})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.stay.id))
        self.assertEqual(self.client.get("/api/v1/staff/stays/", {"ordering": "owner__password"}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/staff/stays/", {"host": "invalid"}).status_code, 400)

    def test_notes_rejection_suspension_and_restoration(self):
        self.assertEqual(self.post("notes", {"note": "Checked the room photos"}).status_code, 200)
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())
        self.assertEqual(self.post("reject", {"reason": "Incomplete information"}).data["status"], StayStatus.REJECTED)
        submit(self.stay)
        self.assertEqual(self.post("approve").status_code, 200)
        self.assertEqual(self.post("suspend", {"reason": "Investigating a report"}).data["status"], StayStatus.SUSPENDED)
        self.assertEqual(self.post("restore").data["status"], StayStatus.PUBLISHED)
