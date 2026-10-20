from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from datetime import timedelta
from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import User
from stays.models import Stay
from .onboarding_models import OnboardingProspect
from .onboarding import snapshot_hash


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class OnboardingConcurrencyTests(TransactionTestCase):
    def test_simultaneous_claims_create_one_draft(self):
        owner = User.objects.create_user(
            email="claim@example.com", password="x", first_name="Owner", last_name="Test", is_email_verified=True
        )
        p = OnboardingProspect.objects.create(
            business_name="Concurrency test",
            contact_email=owner.email,
            consent_status="GRANTED",
            status="CLAIM_PENDING",
            approved_version=1,
            claim_user=owner,
            claim_expires_at=timezone.now() + timedelta(days=1),
            draft_payload={"name": "Concurrency test", "stay_type": "LODGE", "description": "Owner content"},
        )
        p.approved_hash = snapshot_hash(p)
        p.save()
        barrier = Barrier(2)

        def claim():
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=owner.pk))
                barrier.wait(timeout=10)
                r = client.post(
                    f"/api/v1/onboarding/claims/{p.id}/", {"version": 1, "accept_rights": True}, format="json"
                )
                return r.status_code, str(r.data.get("listing_id"))
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(Stay.objects.count(), 1)
