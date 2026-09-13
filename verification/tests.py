from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from core.choices import VerificationStatus
from properties.models import ListingType, PropertyListing, PropertyType
from .models import RequestStatus, VerificationAuditEvent, VerificationDocument, VerificationRequest, VerificationType


def user(email, staff=False):
    return get_user_model().objects.create_user(
        email=email, password="test-pass-123", first_name="Test", last_name="User",
        is_staff=staff, is_email_verified=True
    )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class VerificationApiTests(APITestCase):
    def setUp(self):
        self.owner = user("owner@example.com")
        self.other = user("other@example.com")
        self.reviewer = user("reviewer@example.com", True)
        self.reviewer.user_permissions.add(Permission.objects.get(codename="review_verificationrequest"))
        self.property = PropertyListing.objects.create(
            owner=self.owner,
            title="Mbabane home",
            listing_type=ListingType.RENT,
            property_type=PropertyType.HOUSE,
            price=5000,
        )

    def test_cannot_request_verification_for_another_users_listing(self):
        self.client.force_authenticate(self.other)
        response = self.client.post(
            "/api/verification/requests/",
            {"verification_type": "PROPERTY", "property": str(self.property.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_eligible_entities_only_include_items_the_applicant_can_manage(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/verification/requests/eligible/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data["properties"]], [str(self.property.id)])
        self.client.force_authenticate(self.other)
        response = self.client.get("/api/verification/requests/eligible/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["properties"], [])

    def test_required_documents_and_immutable_submission(self):
        request = VerificationRequest.objects.create(
            applicant=self.owner, verification_type=VerificationType.PROPERTY, property=self.property
        )
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f"/api/verification/requests/{request.id}/submit/").status_code, 400)
        upload = SimpleUploadedFile("deed.pdf", b"evidence", content_type="application/pdf")
        self.assertEqual(
            self.client.post(
                f"/api/verification/requests/{request.id}/documents/",
                {"document_type": "TITLE_DEED", "file": upload},
                format="multipart",
            ).status_code,
            201,
        )
        self.assertEqual(self.client.post(f"/api/verification/requests/{request.id}/submit/").status_code, 200)
        upload = SimpleUploadedFile("extra.pdf", b"evidence", content_type="application/pdf")
        self.assertEqual(
            self.client.post(
                f"/api/verification/requests/{request.id}/documents/",
                {"document_type": "OTHER", "file": upload},
                format="multipart",
            ).status_code,
            400,
        )

    def test_review_approval_badge_and_suspension_are_audited(self):
        request = VerificationRequest.objects.create(
            applicant=self.owner,
            verification_type=VerificationType.PROPERTY,
            property=self.property,
            status=RequestStatus.SUBMITTED,
        )
        self.client.force_authenticate(self.reviewer)
        response = self.client.post(
            f"/api/moderation/verifications/{request.id}/approve/", {"notes": "Evidence accepted"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.property.refresh_from_db()
        self.assertEqual(self.property.verification_status, VerificationStatus.VERIFIED)
        response = self.client.post(
            f"/api/moderation/verifications/{request.id}/suspend/", {"reason": "New evidence"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.property.refresh_from_db()
        self.assertEqual(self.property.verification_status, VerificationStatus.SUSPENDED)
        self.assertEqual(VerificationAuditEvent.objects.filter(verification_request=request).count(), 2)

    def test_private_document_requires_owner_or_reviewer(self):
        request = VerificationRequest.objects.create(applicant=self.owner, verification_type=VerificationType.IDENTITY)
        document = VerificationDocument.objects.create(
            verification_request=request, document_type="NATIONAL_ID", file=SimpleUploadedFile("id.pdf", b"secret")
        )
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/verification/documents/{document.id}/download/").status_code, 403)

    def test_types_expose_the_configured_upload_limit(self):
        response = self.client.get("/api/verification/types/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 6)
        self.assertEqual(response.data[0]["max_file_size_mb"], 10)

    def test_duplicate_active_request_is_rejected(self):
        VerificationRequest.objects.create(
            applicant=self.owner,
            verification_type=VerificationType.PROPERTY,
            property=self.property,
        )
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/verification/requests/",
            {"verification_type": "PROPERTY", "property": str(self.property.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_changes_request_rejects_group_evidence_and_allows_replacement(self):
        request = VerificationRequest.objects.create(
            applicant=self.owner,
            verification_type=VerificationType.PROPERTY,
            property=self.property,
            status=RequestStatus.SUBMITTED,
        )
        old_document = VerificationDocument.objects.create(
            verification_request=request,
            document_type="TITLE_DEED",
            file=SimpleUploadedFile("deed.pdf", b"old evidence"),
        )
        self.client.force_authenticate(self.reviewer)
        response = self.client.post(
            f"/api/moderation/verifications/{request.id}/request-changes/",
            {
                "notes": "Please upload a clearer image showing all corners.",
                "requirement_keys": ["authority_to_list"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], RequestStatus.CHANGES_REQUESTED)
        old_document.refresh_from_db()
        self.assertEqual(old_document.status, "REJECTED")

        self.client.force_authenticate(self.owner)
        self.assertEqual(
            self.client.post(f"/api/verification/requests/{request.id}/submit/").status_code,
            400,
        )
        replacement = SimpleUploadedFile("authority.pdf", b"new evidence", content_type="application/pdf")
        self.assertEqual(
            self.client.post(
                f"/api/verification/requests/{request.id}/documents/",
                {"document_type": "OWNER_AUTHORIZATION", "file": replacement},
                format="multipart",
            ).status_code,
            201,
        )
        self.assertEqual(
            self.client.post(f"/api/verification/requests/{request.id}/submit/").status_code,
            200,
        )

    def test_business_verification_can_be_created_for_the_applicant(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/verification/requests/",
            {"verification_type": "BUSINESS"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
