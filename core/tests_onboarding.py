import hashlib
import io
import tempfile
from datetime import timedelta
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError as ModelError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from accounts.models import User
from agencies.models import Agency
from stays.models import Stay, StayListingAddOn
from properties.models import PropertyListing
from .onboarding_models import OnboardingProspect as Prospect, OnboardingPreview as Preview
from .social import public_https, facebook_url, instagram_url, tiktok_url, whatsapp_number


class SocialValidationTests(SimpleTestCase):
    def test_valid_destinations(self):
        for validator, value in [
            (public_https, "https://business.co.sz/about"),
            (facebook_url, "https://www.facebook.com/business"),
            (instagram_url, "https://instagram.com/business"),
            (tiktok_url, "https://www.tiktok.com/@business"),
            (whatsapp_number, "+26876123456"),
        ]:
            self.assertEqual(validator(value), value)

    def test_unsafe_destinations(self):
        for url in [
            "http://example.com",
            "javascript:alert(1)",
            "data:text/plain,x",
            "https://localhost/a",
            "https://127.0.0.1",
            "https://192.168.0.1",
            "https://[::1]",
            "https://user:pass@example.com",
            "https://business.local",
            "https://2130706433",
            "https://example.com:123",
            "https://example.com\\@evil.com",
        ]:
            with self.subTest(url=url), self.assertRaises(ModelError):
                public_https(url)
        for url in [
            "https://facebook.com.evil.com/business",
            "https://evilfacebook.com/business",
            "https://facebook.com/l.php?u=https://evil.com",
            "https://facebook.com",
        ]:
            with self.subTest(url=url), self.assertRaises(ModelError):
                facebook_url(url)
        for phone in ["76123456", "+012345678", "+26876", "https://wa.me/26876123456"]:
            with self.subTest(phone=phone), self.assertRaises(ModelError):
                whatsapp_number(phone)


class OnboardingTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_superuser(
            email="staff@example.com", password="x", first_name="S", last_name="T"
        )
        self.owner = User.objects.create_user(
            email="owner@example.com", password="x", first_name="O", last_name="W", is_email_verified=True
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="x", first_name="N", last_name="O", is_email_verified=True
        )
        self.client.force_authenticate(self.staff)
        self.base = "/api/v1/staff/onboarding/"
        r = self.client.post(
            self.base,
            {
                "business_name": "Private lodge",
                "contact_email": self.owner.email,
                "consent_status": "GRANTED",
                "consent_evidence": "Owner gave written permission",
                "source_evidence": "Owner supplied text by signed email",
                "draft_payload": {
                    "name": "Private lodge",
                    "description": "Owner supplied content",
                    "stay_type": "LODGE",
                    "town": "Mbabane",
                    "region": "Hhohho",
                },
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.id = r.data["id"]
        self.version = r.data["version"]

    def action(self, name, **body):
        return self.client.post(f"{self.base}{self.id}/{name}/", {"version": self.version, **body}, format="json")

    def issue(self):
        self.assertEqual(self.action("prepare").status_code, 200)
        r = self.action("issue")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data["token"]

    def approve(self):
        self.action("prepare")
        r = self.action(
            "approve", evidence="Signed owner approval, identity checked by video and registry", rights_confirmed=True
        )
        self.assertEqual(r.status_code, 200, r.data)

    def invite(self):
        self.approve()
        r = self.action("invite", evidence="Verified owner identity and title via signed documentation")
        self.assertEqual(r.status_code, 200, r.data)

    def test_tokens_are_hashed_revocable_and_private(self):
        token = self.issue()
        preview = Preview.objects.get(prospect_id=self.id)
        self.assertEqual(preview.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(self.client.get(self.base + str(self.id) + "/").data))
        self.client.force_authenticate(None)
        r = self.client.post("/api/v1/onboarding/preview/", {"token": token}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Cache-Control"], "private, no-store")
        self.assertIn("noindex", r["X-Robots-Tag"])
        self.assertNotIn("contact_email", r.data)
        self.assertNotIn("owner@example.com", str(r.data))
        self.client.force_authenticate(self.staff)
        self.action("revoke")
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": token}).status_code, 404)

    def test_expired_and_rotated_tokens(self):
        token = self.issue()
        other = self.action("issue").data["token"]
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": token}).status_code, 404)
        Preview.objects.filter(prospect_id=self.id).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": other}).status_code, 404)

    def test_revision_invalidates_approval_and_link(self):
        token = self.issue()
        self.approve()
        r = self.client.patch(
            self.base + str(self.id) + "/", {"version": self.version, "notes": "Revised source"}, format="json"
        )
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["approved_version"])
        self.assertEqual(r.data["version"], 2)
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": token}).status_code, 404)
        self.assertEqual(self.action("approve").status_code, 409)

    def test_staff_permissions_and_seeker_exclusion(self):
        for actor in [None, self.owner]:
            self.client.force_authenticate(actor)
            self.assertIn(self.client.get(self.base).status_code, [401, 403])
        limited = User.objects.create_user(
            email="limited@example.com", password="x", first_name="L", last_name="S", is_staff=True
        )
        self.client.force_authenticate(limited)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        limited.user_permissions.add(Permission.objects.get(codename="view_onboardingprospect"))
        limited = User.objects.get(pk=limited.pk)
        self.client.force_authenticate(limited)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.action("issue").status_code, 403)

    def test_consent_is_independent_and_audited(self):
        self.client.patch(
            self.base + str(self.id) + "/",
            {"version": 1, "consent_status": "WITHDRAWN", "consent_evidence": "Owner withdrew in writing"},
            format="json",
        )
        self.version = 2
        self.assertEqual(self.action("prepare").status_code, 400)
        p = Prospect.objects.get(pk=self.id)
        self.assertEqual(p.consent_status, "WITHDRAWN")
        self.assertEqual(p.audit.first().evidence["previous_consent"], "GRANTED")

    def test_injection_rejected(self):
        for key in ["owner", "agency", "status", "is_verified", "featured", "images"]:
            r = self.client.patch(
                self.base + str(self.id) + "/", {"version": 1, "draft_payload": {key: "PUBLISHED"}}, format="json"
            )
            self.assertEqual(r.status_code, 400, (key, r.data))

    def test_claim_requires_bound_verified_owner_and_is_idempotent(self):
        self.invite()
        url = f"/api/v1/onboarding/claims/{self.id}/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url, {"version": 1, "accept_rights": True}, format="json").status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(url, {"version": 1}, format="json").status_code, 400)
        r = self.client.post(url, {"version": 1, "accept_rights": True}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        again = self.client.post(url, {"version": 1, "accept_rights": True}, format="json")
        self.assertEqual(str(again.data["listing_id"]), str(r.data["listing_id"]))
        listing = Stay.objects.get(pk=r.data["listing_id"])
        self.assertEqual(listing.status, "DRAFT")
        self.assertEqual(listing.owner, self.owner)
        self.assertEqual(listing.verification_status, "UNVERIFIED")
        self.assertEqual(Stay.objects.count(), 1)
        self.assertEqual(StayListingAddOn.objects.count(), 0)

    def test_invitation_requires_verified_contact_and_agency_membership(self):
        self.approve()
        self.owner.is_email_verified = False
        self.owner.save()
        self.assertEqual(
            self.action("invite", evidence="Identity and ownership checked independently").status_code, 400
        )
        self.owner.is_email_verified = True
        self.owner.save()
        agency = Agency.objects.create(name="Other business", slug="other-business")
        self.assertEqual(
            self.action(
                "invite", agency=str(agency.id), evidence="Identity and ownership checked independently"
            ).status_code,
            403,
        )

    def test_private_images_require_rights_and_never_have_public_urls(self):
        out = io.BytesIO()
        Image.new("RGB", (8, 8)).save(out, format="PNG")
        data = {
            "version": "1",
            "image": SimpleUploadedFile("photo.png", out.getvalue(), "image/png"),
            "source": "Owner camera",
            "permission_evidence": "Signed permission",
            "caption": "Front view",
        }
        r = self.client.post(self.base + str(self.id) + "/image/", data, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.version = 2
        self.assertNotIn("content", str(r.data["images"]))
        self.assertNotIn("http", str(r.data["images"]))
        token = self.issue()
        r = self.client.post("/api/v1/onboarding/preview/", {"token": token})
        self.assertTrue(r.data["images"][0]["data"].startswith("data:image/jpeg;base64,"))

    def test_preview_never_creates_inventory_or_booking(self):
        self.issue()
        self.assertFalse(Stay.objects.exists())
        self.assertFalse(PropertyListing.objects.exists())
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/stays/").data["count"], 0)
        self.assertEqual(self.client.get("/api/v1/properties/").data["count"], 0)
        self.assertEqual(self.client.get(f"/api/v1/stays/{self.id}/").status_code, 404)

    def test_preview_rate_limit(self):
        for _ in range(30):
            self.client.post("/api/v1/onboarding/preview/", {"token": "x" * 43})
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": "x" * 43}).status_code, 429)

    def test_close_revokes_and_delete_is_scoped(self):
        token = self.issue()
        self.action("transition", status="CLOSED", evidence="Prospect declined")
        self.assertEqual(self.client.post("/api/v1/onboarding/preview/", {"token": token}).status_code, 404)
        self.assertEqual(
            self.client.delete(self.base + str(self.id) + "/", {"version": 2}, format="json").status_code, 204
        )

    def test_property_handoff_validates_price_and_stays_draft(self):
        p = Prospect.objects.get(pk=self.id)
        p.kind = "PROPERTY"
        p.draft_payload = {
            "title": "Private house",
            "description": "Supplied description",
            "listing_type": "RENT",
            "property_type": "HOUSE",
            "price": "5000",
        }
        p.save()
        self.invite()
        self.client.force_authenticate(self.owner)
        r = self.client.post(
            f"/api/v1/onboarding/claims/{self.id}/", {"version": 1, "accept_rights": True}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        listing = PropertyListing.objects.get(pk=r.data["listing_id"])
        self.assertEqual(listing.status, "DRAFT")
        self.assertEqual(listing.availability_status, "UNKNOWN")

    def test_social_writes_use_existing_ownership_permissions(self):
        stay = Stay.objects.create(owner=self.owner, name="Owner lodge", stay_type="LODGE")
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.patch(
                f"/api/v1/stays/{stay.id}/", {"facebook_url": "https://facebook.com/lodge"}, format="json"
            ).status_code,
            403,
        )
        self.client.force_authenticate(self.owner)
        self.assertEqual(
            self.client.patch(
                f"/api/v1/stays/{stay.id}/", {"facebook_url": "https://evilfacebook.com/lodge"}, format="json"
            ).status_code,
            400,
        )
        r = self.client.patch(
            f"/api/v1/stays/{stay.id}/", {"facebook_url": "https://facebook.com/lodge"}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(f"/api/v1/stays/{stay.id}/").status_code, [403, 404])

    def test_photo_handoff_requires_explicit_owner_opt_in(self):
        from .onboarding_models import OnboardingImage

        out = io.BytesIO()
        Image.new("RGB", (8, 8)).save(out, format="JPEG")
        OnboardingImage.objects.create(
            prospect_id=self.id,
            content=out.getvalue(),
            source="Owner camera",
            permission_evidence="Signed photo permission",
        )
        self.invite()
        self.client.force_authenticate(self.owner)
        r = self.client.post(
            f"/api/v1/onboarding/claims/{self.id}/", {"version": 1, "accept_rights": True}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Stay.objects.get(pk=r.data["listing_id"]).images.count(), 0)

    def test_opted_in_photos_use_normal_serializer_once(self):
        from .onboarding_models import OnboardingImage

        out = io.BytesIO()
        Image.new("RGB", (8, 8)).save(out, format="JPEG")
        OnboardingImage.objects.create(
            prospect_id=self.id,
            content=out.getvalue(),
            source="Owner camera",
            permission_evidence="Signed photo permission",
        )
        self.invite()
        self.client.force_authenticate(self.owner)
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            url = f"/api/v1/onboarding/claims/{self.id}/"
            body = {"version": 1, "accept_rights": True, "use_approved_photos": True}
            r = self.client.post(url, body, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(self.client.post(url, body, format="json").status_code, 200)
            self.assertEqual(Stay.objects.get(pk=r.data["listing_id"]).images.count(), 1)
