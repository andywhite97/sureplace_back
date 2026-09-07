from django.test import TestCase

from accounts.models import User
from core.choices import VerificationStatus
from .models import Agency, AgentProfile


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
