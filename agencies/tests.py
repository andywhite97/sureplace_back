from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from core.choices import VerificationStatus
from notifications.models import EmailDelivery
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
