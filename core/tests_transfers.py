from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APITestCase
from accounts.models import User
from agencies.models import Agency, AgentProfile
from properties.tests import make_listing
from properties.models import PropertyListing
from stays.models import Stay
from core.models import ListingTransfer


class ListingTransferTests(APITestCase):
    def setUp(self):
        self.owner = self.user("owner")
        self.recipient = self.user("recipient")
        self.other = self.user("other")
        self.listing = make_listing(self.owner)
        self.client.force_authenticate(self.owner)
        self.url = "/api/v1/listing-transfers/"

    def user(self, name):
        return User.objects.create_user(
            email=f"{name}@example.com", first_name=name, last_name="Test", is_email_verified=True
        )

    def create(self, **kwargs):
        return self.client.post(
            self.url, {"kind": "property", "listing_id": str(self.listing.pk), "email": self.recipient.email, **kwargs}
        )

    def resolve(self, transfer_id, action):
        return self.client.post(f"{self.url}{transfer_id}/", {"action": action})

    def test_owner_to_user_requires_acceptance_and_preserves_identity(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.owner, self.owner)
        slug, public_id = self.listing.slug, self.listing.public_id
        self.client.force_authenticate(self.recipient)
        response = self.resolve(response.data["id"], "accept")
        self.assertEqual(response.status_code, 200, response.data)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.owner, self.recipient)
        self.assertEqual((self.listing.slug, self.listing.public_id), (slug, public_id))
        self.assertIsNone(self.listing.agent)
        self.assertEqual(self.listing.verification_status, "UNVERIFIED")
        self.assertEqual(self.client.get("/api/v1/properties/mine/").data["count"], 1)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(f"/api/v1/properties/{slug}/", {"title": "Old owner edit"}).status_code, 403)

    def test_stranger_cannot_send_or_accept_or_read(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.create().status_code, 403)
        self.client.force_authenticate(self.owner)
        transfer = self.create().data["id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 403)
        self.assertEqual(self.client.get(self.url).data, [])

    def test_duplicate_self_and_missing_target_rejected(self):
        self.assertEqual(self.create(email=self.owner.email).status_code, 400)
        self.assertEqual(self.create(email="absent@example.com").status_code, 400)
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 400)

    def test_cancel_decline_expiry_and_replay(self):
        transfer = self.create().data["id"]
        self.assertEqual(self.resolve(transfer, "cancel").status_code, 200)
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 400)
        self.client.force_authenticate(self.owner)
        transfer = self.create().data["id"]
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "decline").status_code, 200)
        self.client.force_authenticate(self.owner)
        transfer = self.create().data["id"]
        ListingTransfer.objects.filter(pk=transfer).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(self.url).data[0]["status"], "EXPIRED")
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 400)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.create().status_code, 201)

    def test_user_to_agency_only_admin_can_accept(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        AgentProfile.objects.create(user=self.recipient, agency=agency, role="OWNER")
        AgentProfile.objects.create(user=self.other, agency=agency, role="AGENT")
        response = self.client.post(
            self.url, {"kind": "property", "listing_id": str(self.listing.pk), "agency_id": str(agency.pk)}
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.resolve(response.data["id"], "accept").status_code, 403)
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(response.data["id"], "accept").status_code, 200)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.agency, agency)
        self.assertEqual(self.listing.owner, self.recipient)
        self.assertEqual(self.client.get("/api/v1/properties/mine/", {"agency": str(agency.pk)}).data["count"], 1)

    def test_agency_agent_cannot_transfer_even_if_original_owner(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        AgentProfile.objects.create(user=self.owner, agency=agency, role="AGENT")
        self.listing.agency = agency
        self.listing.save()
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.client.get(self.url + "options/").data["listings"], [])

    def test_agency_admin_can_transfer_to_individual(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        AgentProfile.objects.create(user=self.owner, agency=agency, role="ADMIN")
        self.listing.agency = agency
        self.listing.save()
        transfer = self.create().data["id"]
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 200)
        self.listing.refresh_from_db()
        self.assertIsNone(self.listing.agency)
        self.assertEqual(self.listing.owner, self.recipient)

    def test_revoked_sender_access_blocks_acceptance(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        member = AgentProfile.objects.create(user=self.owner, agency=agency, role="ADMIN")
        self.listing.agency = agency
        self.listing.save()
        transfer = self.create().data["id"]
        member.is_active = False
        member.save()
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 400)
        self.assertEqual(ListingTransfer.objects.get(pk=transfer).status, "PENDING")

    def test_stay_transfer(self):
        stay = Stay.objects.create(owner=self.owner, name="Test Lodge", stay_type="LODGE")
        response = self.create(kind="stay", listing_id=str(stay.pk))
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(response.data["id"], "accept").status_code, 200)
        stay.refresh_from_db()
        self.assertEqual(stay.owner, self.recipient)

    def test_agency_changes_must_use_transfer(self):
        agency = Agency.objects.create(name="Agency", slug="agency")
        AgentProfile.objects.create(user=self.owner, agency=agency, role="OWNER")
        self.assertEqual(
            self.client.patch(f"/api/v1/properties/{self.listing.slug}/", {"agency": str(agency.pk)}).status_code, 400
        )
        stay = Stay.objects.create(owner=self.owner, name="Test Lodge", stay_type="LODGE")
        self.assertEqual(self.client.patch(f"/api/v1/stays/{stay.slug}/", {"agency": str(agency.pk)}).status_code, 400)

    def test_capacity_failure_keeps_request_and_ownership(self):
        from unittest.mock import patch
        from rest_framework.exceptions import ValidationError

        transfer = self.create().data["id"]
        self.client.force_authenticate(self.recipient)
        with patch.object(PropertyListing, "save", side_effect=ValidationError("Recipient capacity reached.")):
            self.assertEqual(self.resolve(transfer, "accept").status_code, 400)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.owner, self.owner)
        self.assertEqual(ListingTransfer.objects.get(pk=transfer).status, "PENDING")

    def test_unverified_user_cannot_accept(self):
        transfer = self.create().data["id"]
        self.recipient.is_email_verified = False
        self.recipient.save()
        self.client.force_authenticate(self.recipient)
        self.assertEqual(self.resolve(transfer, "accept").status_code, 403)

    def test_real_publication_capacity_is_enforced(self):
        from properties.models import ListingStatus
        from properties.entitlement_models import PropertyPlan

        limit = PropertyPlan.objects.get(code="INDIVIDUAL_FREE").active_listing_limit
        for index in range(limit):
            make_listing(self.recipient, title=f"Existing {index}", status=ListingStatus.PUBLISHED)
        self.listing.status = ListingStatus.PUBLISHED
        self.listing.save()
        transfer = self.create().data["id"]
        self.client.force_authenticate(self.recipient)
        response = self.resolve(transfer, "accept")
        self.assertEqual(response.status_code, 400, response.data)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.owner, self.owner)
        self.assertEqual(ListingTransfer.objects.get(pk=transfer).status, "PENDING")
