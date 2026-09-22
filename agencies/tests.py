from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from core.choices import VerificationStatus
from notifications.models import EmailDelivery
from properties.models import PropertyListing
from stays.models import Stay
from .models import Agency, AgencyInvitation, AgentProfile


class AgencyModelTests(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(
            name="Lusito Estates", slug="lusito-estates", town="Mbabane", region="Hhohho"
        )
        self.user = User.objects.create_user(
            email="agent@example.com", password="StrongPass123!", first_name="Sibusiso", last_name="Mamba"
        )

    def test_agency_integrity(self):
        self.assertEqual(str(self.agency), "Lusito Estates")
        self.assertEqual(self.agency.verification_status, VerificationStatus.UNVERIFIED)
        self.assertTrue(self.agency.is_active)

    def test_agent_profile_relationships(self):
        profile = AgentProfile.objects.create(user=self.user, agency=self.agency, professional_reference="REA-001")
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.agency, self.agency)
        self.assertEqual(list(self.agency.agents.all()), [profile])
        self.assertEqual(list(self.user.agent_profiles.all()), [profile])


class AgencyApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Nomsa",
            last_name="Dlamini",
            is_email_verified=True,
        )
        self.payload = {
            "name": "Lusito Estates",
            "trading_name": "Lusito Estates Eswatini",
            "description": "Residential and hospitality property specialists.",
            "email": "hello@lusito.example",
            "phone": "+26876123456",
            "whatsapp_number": "+26876123456",
            "website": "https://lusito.example",
            "region": "Hhohho",
            "town": "Mbabane",
            "suburb": "Sidwashini",
            "address": "1 Agency Lane",
        }

    @override_settings(EMAIL_PROVIDER="django", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_verified_user_can_create_agency_and_becomes_owner(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("v1:agency-list"), self.payload, format="json")
        self.assertEqual(response.status_code, 201)
        agency = Agency.objects.get(name="Lusito Estates")
        self.assertEqual(agency.verification_status, VerificationStatus.UNVERIFIED)
        profile = AgentProfile.objects.get(user=self.user, agency=agency)
        self.assertEqual(profile.role, AgentProfile.Role.OWNER)

    def test_unverified_user_is_blocked_from_agency_creation(self):
        self.user.is_email_verified = False
        self.user.save(update_fields=["is_email_verified"])
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse("v1:agency-list"), self.payload, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "email_not_verified")
        self.assertIn("before creating an agency", response.data["message"])

    @override_settings(EMAIL_PROVIDER="django", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_owner_can_update_invite_and_member_can_accept(self):
        agency = Agency.objects.create(name="Lusito Estates", slug="lusito-estates")
        AgentProfile.objects.create(user=self.user, agency=agency, role=AgentProfile.Role.OWNER)
        invited = User.objects.create_user(
            email="agent@example.com",
            password="StrongPass123!",
            first_name="Sibusiso",
            last_name="Mamba",
            is_email_verified=True,
        )
        self.client.force_authenticate(self.user)
        update = self.client.patch(reverse("v1:agency-detail", args=[agency.id]), {"town": "Manzini"}, format="json")
        self.assertEqual(update.status_code, 200)

        invite = self.client.post(
            reverse("v1:agency-invitations", args=[agency.id]), {"email": invited.email, "role": "ADMIN"}, format="json"
        )
        self.assertEqual(invite.status_code, 201)
        invitation = AgencyInvitation.objects.get(email=invited.email)
        self.assertEqual(EmailDelivery.objects.get().template_key, "agency.invitation")

        self.client.force_authenticate(invited)
        accepted = self.client.post(
            reverse("v1:agency-invitation-accept"), {"token": str(invitation.token)}, format="json"
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(AgentProfile.objects.get(user=invited, agency=agency).role, AgentProfile.Role.ADMIN)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, AgencyInvitation.Status.ACCEPTED)

    def test_agent_cannot_edit_agency_or_invite(self):
        agency = Agency.objects.create(name="Lusito Estates", slug="lusito-estates")
        AgentProfile.objects.create(user=self.user, agency=agency, role=AgentProfile.Role.AGENT)
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.patch(
                reverse("v1:agency-detail", args=[agency.id]), {"town": "Manzini"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("v1:agency-invitations", args=[agency.id]),
                {"email": "new@example.com", "role": "AGENT"},
                format="json",
            ).status_code,
            403,
        )

    def test_last_owner_cannot_be_removed(self):
        agency = Agency.objects.create(name="Lusito Estates", slug="lusito-estates")
        profile = AgentProfile.objects.create(user=self.user, agency=agency, role=AgentProfile.Role.OWNER)
        self.client.force_authenticate(self.user)
        response = self.client.delete(reverse("v1:agency-remove-member", args=[agency.id, profile.id]))
        self.assertEqual(response.status_code, 409)

    def test_management_dashboard_uses_onboarding_until_a_real_context_exists(self):
        self.client.force_authenticate(self.user)

        onboarding = self.client.get(reverse("v1:management-dashboard"))
        self.assertEqual(onboarding.status_code, 200)
        self.assertEqual(onboarding.data["mode"], "onboarding")

        self.user.onboarding_intents = ["PROPERTY_OWNER"]
        self.user.save(update_fields=["onboarding_intents"])
        individual = self.client.get(reverse("v1:management-dashboard"))
        self.assertEqual(individual.status_code, 200)
        self.assertEqual(individual.data["mode"], "dashboard")
        self.assertEqual(individual.data["context"]["kind"], "individual")
        self.assertEqual(individual.data["stats"]["total_listings"], 0)

    def test_management_dashboard_scopes_listings_and_paginates_each_context(self):
        agency = Agency.objects.create(name="Lusito Estates", slug="lusito-estates")
        AgentProfile.objects.create(user=self.user, agency=agency, role=AgentProfile.Role.OWNER)
        independent = PropertyListing.objects.create(
            owner=self.user,
            title="Independent home",
            listing_type="RENT",
            property_type="HOUSE",
            price=Decimal("5000.00"),
            town="Mbabane",
        )
        agency_listing = PropertyListing.objects.create(
            owner=self.user,
            agency=agency,
            title="Agency home",
            listing_type="SALE",
            property_type="HOUSE",
            price=Decimal("900000.00"),
            town="Manzini",
        )
        independent_stay = Stay.objects.create(
            owner=self.user,
            name="Independent stay",
            stay_type="GUEST_HOUSE",
            town="Mbabane",
        )
        agency_stay = Stay.objects.create(
            owner=self.user,
            agency=agency,
            name="Agency stay",
            stay_type="HOTEL",
            town="Manzini",
        )
        self.client.force_authenticate(self.user)

        individual_response = self.client.get(
            reverse("v1:management-dashboard"),
            {"context": "individual", "page_size": 1, "type": "property"},
        )
        agency_response = self.client.get(
            reverse("v1:management-dashboard"),
            {"context": f"agency:{agency.id}", "page_size": 1, "type": "property"},
        )

        self.assertEqual(individual_response.status_code, 200)
        self.assertEqual(individual_response.data["listings"]["count"], 1)
        self.assertEqual(individual_response.data["listings"]["results"][0]["id"], str(independent.id))
        self.assertEqual(agency_response.status_code, 200)
        self.assertEqual(agency_response.data["listings"]["count"], 1)
        self.assertEqual(agency_response.data["listings"]["results"][0]["id"], str(agency_listing.id))

        individual_properties = self.client.get(reverse("v1:property-mine"), {"context": "individual"})
        agency_properties = self.client.get(reverse("v1:property-mine"), {"agency": str(agency.id)})
        individual_stays = self.client.get(reverse("v1:stay-mine"), {"context": "individual"})
        agency_stays = self.client.get(reverse("v1:stay-mine"), {"agency": str(agency.id)})

        self.assertEqual([item["id"] for item in individual_properties.data["results"]], [str(independent.id)])
        self.assertEqual([item["id"] for item in agency_properties.data["results"]], [str(agency_listing.id)])
        self.assertEqual([item["id"] for item in individual_stays.data["results"]], [str(independent_stay.id)])
        self.assertEqual([item["id"] for item in agency_stays.data["results"]], [str(agency_stay.id)])

    def test_management_dashboard_rejects_an_unauthorized_agency_context(self):
        agency = Agency.objects.create(name="Another Agency", slug="another-agency")
        self.client.force_authenticate(self.user)

        response = self.client.get(
            reverse("v1:management-dashboard"),
            {"context": f"agency:{agency.id}"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse("v1:property-mine"), {"agency": agency.id}).status_code, 403)
        self.assertEqual(self.client.get(reverse("v1:stay-mine"), {"agency": agency.id}).status_code, 403)


class PublicAgentApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Nomsa",
            last_name="Dlamini",
            is_email_verified=True,
        )
        self.agency = Agency.objects.create(
            name="Lusito Estates",
            slug="lusito-estates",
            region="Hhohho",
            town="Mbabane",
            description="Property specialists in Eswatini.",
            verification_status=VerificationStatus.VERIFIED,
        )
        self.agent_user = User.objects.create_user(
            email="agent@example.com",
            password="StrongPass123!",
            first_name="Sibusiso",
            last_name="Mamba",
            is_email_verified=True,
        )
        self.agent = AgentProfile.objects.create(
            user=self.agent_user,
            agency=self.agency,
            role=AgentProfile.Role.AGENT,
            bio="Trusted property advisor.",
            verification_status=VerificationStatus.VERIFIED,
            is_active=True,
        )
        self.listing = PropertyListing.objects.create(
            owner=self.owner,
            agency=self.agency,
            agent=self.agent,
            title="Modern Family Home",
            description="A great place to call home.",
            listing_type="SALE",
            property_type="HOUSE",
            price=Decimal("2500000.00"),
            currency="SZL",
            region="Hhohho",
            town="Mbabane",
            suburb="Sidwashini",
            address="3 Main Road",
            status="PUBLISHED",
            verification_status=VerificationStatus.VERIFIED,
            featured=True,
        )

    def test_public_agents_listing_and_detail_are_available(self):
        response = self.client.get(reverse("v1:agent-list"))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["count"], 0)
        first = response.data["results"][0]
        self.assertEqual(first["name"], "Sibusiso Mamba")
        self.assertTrue(first["verified_agent"])
        self.assertTrue(first["verified_agency"])
        self.assertIn("Mbabane", first["service_areas"])
        self.assertEqual(first["agency"]["name"], "Lusito Estates")

        detail = self.client.get(reverse("v1:agent-detail", args=[self.agent.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["id"], str(self.agent.pk))
        self.assertEqual(detail.data["agency"]["name"], "Lusito Estates")
        self.assertEqual(detail.data["active_listings_count"], 1)
        self.assertEqual(detail.data["active_listings"][0]["title"], "Modern Family Home")
