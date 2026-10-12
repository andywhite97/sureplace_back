from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from threading import Barrier
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib import admin
from django.test import RequestFactory
from .pricing_admin import PropertyListingAddOnAdmin, PropertySubscriptionAdmin

from accounts.models import User
from agencies.models import Agency, AgentProfile
from notifications.models import Notification
from .models import PropertyAddOnPackage, PropertySubscription, PropertyListingAddOn, PropertyListing
from .entitlements import summary, grant_package, PropertyListingLimitReached
from .services import confirm_availability, mark_unavailable, submit_listing
from .tasks import process_property_entitlements
from .tests import make_listing, listing_data


def seed_catalogue():
    import_module("properties.migrations.0008_property_pricing_catalogue").seed(
        apps, SimpleNamespace(connection=connection)
    )


def user(email="owner@pricing.test", **kwargs):
    return User.objects.create_user(
        email=email, first_name="Property", last_name="Owner", is_email_verified=True, **kwargs
    )


class EntitlementTests(TestCase):
    def setUp(self):
        self.owner = user()
        self.staff = user("staff@pricing.test", is_staff=True)
        self.agency = Agency.objects.create(name="Pricing Agency", slug="pricing-agency")
        self.agent = AgentProfile.objects.create(user=self.owner, agency=self.agency)
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def live(self, **kwargs):
        return make_listing(kwargs.pop("owner", self.owner), status="PUBLISHED", **kwargs)

    def grant(self, code="SINGLE_EXTRA", **kwargs):
        return grant_package(
            PropertyAddOnPackage.objects.get(pk=code),
            actor=self.staff,
            reason="Verified offline entitlement grant",
            account=kwargs.pop("account", self.owner),
            **kwargs,
        )

    def subscribe(self, code="STARTER", **kwargs):
        return PropertySubscription.objects.create(
            account=kwargs.pop("account", self.owner),
            plan_id=code,
            granted_by=self.staff,
            grant_reason="Offline grant",
            expires_at=timezone.now() + timedelta(days=30),
            **kwargs,
        )

    def test_individual_free_and_full_publish(self):
        self.live()
        self.live()
        with self.assertRaises(PropertyListingLimitReached) as error:
            self.live()
        self.assertEqual(error.exception.detail["listing_limit"], 2)
        self.assertIs(error.exception.detail["upgrade_available"], True)
        s = summary(self.owner.pk)
        self.assertEqual(s["remaining_publication_capacity"], 0)
        self.assertEqual(s["usage_percent"], 100)

    def test_multiple_agents_share_agency_allowance_and_personal_is_separate(self):
        other = user("agent-two@pricing.test")
        profile = AgentProfile.objects.create(user=other, agency=self.agency)
        for i in range(5):
            self.live(owner=other if i % 2 else self.owner, agency=self.agency, agent=profile if i % 2 else self.agent)
        self.assertEqual(summary(agency_id=self.agency.pk)["active_listing_count"], 5)
        with self.assertRaises(PropertyListingLimitReached):
            self.live(agency=self.agency, agent=self.agent)
        self.live()
        self.live()
        self.assertEqual(summary(self.owner.pk)["active_listing_count"], 2)

    def test_excluded_inventory_and_availability_reentry(self):
        for status in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "PAUSED", "EXPIRED", "REJECTED", "SUSPENDED"]:
            make_listing(self.owner, status=status)
        hidden = self.live(availability_status="UNAVAILABLE")
        self.live()
        self.live()
        with self.assertRaises(PropertyListingLimitReached):
            confirm_availability(hidden)
        self.assertEqual(summary(self.owner.pk)["active_listing_count"], 2)

    def test_draft_create_edit_and_delete_at_capacity(self):
        self.live()
        self.live()
        response = self.client.post("/api/v1/properties/", listing_data(), format="json")
        self.assertEqual(response.status_code, 201)
        pk = response.data["id"]
        self.assertEqual(
            self.client.patch(f"/api/v1/properties/{pk}/", {"title": "Edited draft"}, format="json").status_code, 200
        )
        response = self.client.post(f"/api/v1/properties/{pk}/submit/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "PROPERTY_LISTING_LIMIT_REACHED")
        self.assertEqual(response.data["active_listings"], 2)
        self.assertEqual(self.client.delete(f"/api/v1/properties/{pk}/").status_code, 204)

    def test_patch_cannot_publish_or_forge_entitlement(self):
        p = make_listing(self.owner)
        response = self.client.patch(
            f"/api/v1/properties/{p.pk}/", {"status": "PUBLISHED", "plan": "AGENCY_PLUS", "paid": True}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, "DRAFT")
        self.assertFalse(PropertySubscription.objects.exists())

    def test_cross_agency_scope_and_mutation_denied(self):
        other = Agency.objects.create(name="Other", slug="other")
        self.assertEqual(self.client.get(f"/api/v1/account/property-entitlements/?agency={other.pk}").status_code, 403)
        self.assertEqual(
            self.client.post("/api/v1/properties/", listing_data(agency=str(other.pk)), format="json").status_code, 400
        )
        self.assertEqual(self.client.get("/api/v1/account/property-entitlements/?agency=invalid").status_code, 400)
        self.assertEqual(
            self.client.get(f"/api/v1/account/property-entitlements/?agency={self.agency.pk}").data[
                "base_listing_allowance"
            ],
            5,
        )

    def test_revoked_agent_cannot_manage_agency_property(self):
        p = make_listing(self.owner, agency=self.agency, agent=self.agent)
        self.agent.is_active = False
        self.agent.save()
        self.assertEqual(self.client.post(f"/api/v1/properties/{p.pk}/confirm-availability/").status_code, 403)

    def test_paid_allowance_replaces_free(self):
        self.subscribe()
        for _ in range(10):
            self.live()
        self.assertEqual(summary(self.owner.pk)["base_listing_allowance"], 10)
        with self.assertRaises(PropertyListingLimitReached):
            self.live()

    def test_agency_plus_individual_disallowed_and_xor_owner(self):
        with self.assertRaises(DjangoValidationError):
            self.subscribe("AGENCY_PLUS")
        with self.assertRaises(DjangoValidationError):
            self.subscribe(agency=self.agency)
        with self.assertRaises(DjangoValidationError):
            self.subscribe(account=None)

    def test_bundle_allocation_and_duplicate_purchase_are_auditable(self):
        units = self.grant("TRIPLE_EXTRA")
        self.assertEqual(len(units), 3)
        self.assertEqual(sum(u.amount for u in units), Decimal("129"))
        again = self.grant("TRIPLE_EXTRA", reference=units[0].purchase_reference)
        self.assertEqual({u.pk for u in units}, {u.pk for u in again})
        self.live()
        self.live()
        p = self.live()
        active = PropertyListingAddOn.objects.get(status="ACTIVE")
        self.assertEqual(active.assigned_property_id, p.pk)
        self.assertEqual(active.expires_at - active.activated_at, timedelta(days=90))
        self.assertEqual(summary(self.owner.pk)["unused_extra_allowances"], 2)
        self.assertEqual(summary(self.owner.pk)["remaining_publication_capacity"], 2)
        p.title = "Edit extra"
        p.save()
        self.assertEqual(PropertyListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    def test_unused_bundle_waits_and_optional_purchase_validity(self):
        self.grant("TRIPLE_EXTRA")
        self.assertEqual(PropertyListingAddOn.objects.filter(activated_at=None, expires_at=None).count(), 3)
        package = PropertyAddOnPackage.objects.get(pk="SINGLE_EXTRA")
        package.purchase_validity_days = 1
        package.save()
        unit = self.grant()[0]
        unit.activate_before = timezone.now() - timedelta(days=1)
        unit.save()
        self.assertEqual(summary(self.owner.pk)["unused_extra_allowances"], 3)

    def test_bound_units_not_reallocated_when_unavailable(self):
        self.live()
        self.live()
        self.grant()
        extra = self.live()
        mark_unavailable(extra)
        with self.assertRaises(PropertyListingLimitReached):
            self.live()
        confirm_availability(extra)
        self.assertEqual(PropertyListingAddOn.objects.filter(status="ACTIVE").count(), 1)
        extra.status = "PAUSED"
        extra.save()
        response = self.client.get(f"/api/v1/account/property-entitlements/?property={extra.pk}")
        self.assertTrue(response.data["can_publish_property"])
        self.assertEqual(response.data["remaining_publication_capacity"], 0)

    def test_activated_entitlement_history_and_owner_immutable(self):
        self.live()
        self.live()
        self.grant()
        extra = self.live()
        unit = PropertyListingAddOn.objects.get(status="ACTIVE")
        unit.expires_at += timedelta(days=90)
        with self.assertRaises(DjangoValidationError):
            unit.save()
        extra.agency = self.agency
        with self.assertRaises(DjangoValidationError):
            extra.save()

    def expired_extra(self):
        self.live()
        self.live()
        self.grant()
        with patch("properties.entitlements.timezone.now", return_value=timezone.now() - timedelta(days=91)):
            return self.live()

    def test_expiry_pauses_only_specific_extra_and_task_idempotent(self):
        p = self.expired_extra()
        self.assertEqual(process_property_entitlements(), 1)
        self.assertEqual(process_property_entitlements(), 0)
        p.refresh_from_db()
        self.assertEqual(p.status, "PAUSED")
        self.assertEqual(PropertyListing.objects.filter(status="PUBLISHED").count(), 2)
        self.assertEqual(PropertyListingAddOn.objects.get().status, "EXPIRED")
        self.grant()
        submit_listing(p)
        p.status = "PUBLISHED"
        p.save()
        self.assertEqual(PropertyListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    def test_expiry_uses_ordinary_capacity_without_pause(self):
        p = self.expired_extra()
        ordinary = PropertyListing.objects.exclude(pk=p.pk).first()
        mark_unavailable(ordinary)
        process_property_entitlements()
        p.refresh_from_db()
        self.assertEqual(p.status, "PUBLISHED")
        self.assertEqual(summary(self.owner.pk)["active_listing_count"], 2)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_DELIVERY_MODE="sync")
    def test_reminder_and_expiry_notification_idempotency(self):
        self.live()
        self.live()
        self.grant()
        with patch("properties.entitlements.timezone.now", return_value=timezone.now() - timedelta(days=89, hours=1)):
            self.live()
        with self.captureOnCommitCallbacks(execute=True):
            process_property_entitlements()
            process_property_entitlements()
        self.assertEqual(Notification.objects.filter(event_key__startswith="property-addon:").count(), 2)
        unit = PropertyListingAddOn.objects.get()
        with patch("properties.tasks.timezone.now", return_value=unit.expires_at + timedelta(seconds=1)):
            with self.captureOnCommitCallbacks(execute=True):
                process_property_entitlements()
                process_property_entitlements()
        self.assertEqual(Notification.objects.filter(event_key__contains=":expired:").count(), 1)

    def test_subscription_expiry_grace_downgrade_preserves_inventory(self):
        sub = self.subscribe()
        for _ in range(5):
            self.live()
        sub.expires_at = timezone.now() - timedelta(days=1)
        sub.starts_at = timezone.now() - timedelta(days=31)
        sub.save()
        self.assertEqual(summary(self.owner.pk)["subscription_status"], "GRACE")
        sub.expires_at = timezone.now() - timedelta(days=8)
        sub.save()
        s = summary(self.owner.pk)
        self.assertEqual(s["subscription_status"], "EXPIRED")
        self.assertTrue(s["legacy_over_limit"])
        process_property_entitlements()
        self.assertEqual(PropertyListing.objects.filter(status="PUBLISHED").count(), 5)
        p = PropertyListing.objects.first()
        p.title = "Preserved edit"
        p.save()
        with self.assertRaises(PropertyListingLimitReached):
            self.live()

    def test_unauthorized_grants_and_subscription_modification(self):
        with self.assertRaises(Exception):
            grant_package(
                PropertyAddOnPackage.objects.get(pk="SINGLE_EXTRA"),
                actor=self.owner,
                reason="Forged",
                account=self.owner,
            )
        for path in ["/api/v1/account/property-entitlements/", "/api/v1/pricing/properties/"]:
            self.assertEqual(
                self.client.post(path, {"plan": "PROFESSIONAL", "payment_success": True}, format="json").status_code,
                405,
            )
        self.assertFalse(PropertySubscription.objects.exists())

    def test_pricing_serialization_and_authenticated_summary(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/v1/pricing/properties/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["plans"]), 5)
        self.assertEqual(response.data["plans"][2]["price"], "149.00")
        self.assertFalse(response.data["checkout_available"])
        self.assertEqual(self.client.get("/api/v1/account/property-entitlements/").status_code, 401)

    def test_bulk_publication_cannot_bypass_model_guard(self):
        p = make_listing(self.owner)
        with self.assertRaises(DjangoValidationError):
            PropertyListing.objects.filter(pk=p.pk).update(status="PUBLISHED")
        p.status = "PUBLISHED"
        with self.assertRaises(DjangoValidationError):
            PropertyListing.objects.bulk_update([p], ["status"])
        with self.assertRaises(DjangoValidationError):
            PropertyListing.objects.bulk_create([p])

    def test_admin_bundle_form_creates_all_units_with_staff_audit(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        model_admin = PropertyListingAddOnAdmin(PropertyListingAddOn, admin.site)
        Form = model_admin.get_form(request)
        form = Form(
            data={
                "account": self.owner.pk,
                "source_package": "TRIPLE_EXTRA",
                "grant_reason": "Documented admin grant",
                "provider": "offline-reference",
                "transaction_reference": "ADMIN-123",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        model_admin.save_model(request, obj, form, False)
        self.assertEqual(PropertyListingAddOn.objects.count(), 3)
        self.assertEqual(
            PropertyListingAddOn.objects.filter(granted_by=self.staff, grant_reason="Documented admin grant").count(), 3
        )
        self.assertEqual(sum(PropertyListingAddOn.objects.values_list("amount", flat=True)), Decimal("129"))
        self.assertEqual(
            PropertyListingAddOn.objects.filter(
                provider="offline-reference", transaction_reference="ADMIN-123"
            ).count(),
            3,
        )

    def test_admin_subscription_form_requires_reason_and_records_actor(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        Form = PropertySubscriptionAdmin(PropertySubscription, admin.site).get_form(request)
        form = Form(
            data={
                "account": self.owner.pk,
                "plan": "STARTER",
                "status": "ACTIVE",
                "grant_reason": "Admin test",
                "starts_at_0": "2026-10-01",
                "starts_at_1": "12:00:00",
                "expires_at_0": "2026-11-01",
                "expires_at_1": "12:00:00",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.granted_by, self.staff)

    def test_approval_and_restoration_enforce_limit(self):
        self.staff.is_superuser = True
        self.staff.save()
        self.live()
        self.live()
        p = make_listing(self.owner, status="SUBMITTED")
        self.client.force_authenticate(self.staff)
        response = self.client.post(f"/api/v1/staff/properties/{p.pk}/approve/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "PROPERTY_LISTING_LIMIT_REACHED")
        p.refresh_from_db()
        self.assertEqual(p.status, "SUBMITTED")
        p.status = "SUSPENDED"
        p.save()
        response = self.client.post(f"/api/v1/staff/properties/{p.pk}/restore/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "PROPERTY_LISTING_LIMIT_REACHED")

    def test_existing_listing_migration_safety(self):
        historical = (
            MigrationExecutor(connection)
            .loader.project_state([("properties", "0006_propertylisting_availability_reminded_at")])
            .apps.get_model("properties", "PropertyListing")
        )
        for index in range(3):
            historical.objects.create(
                owner_id=self.owner.pk,
                public_id=f"LEGACY-{index}",
                slug=f"legacy-{index}",
                title="Existing",
                listing_type="RENT",
                property_type="HOUSE",
                price="1000",
                status="PUBLISHED",
                availability_status="AVAILABLE",
            )
        seed_catalogue()
        self.assertEqual(PropertyListing.objects.filter(status="PUBLISHED").count(), 3)
        self.assertTrue(summary(self.owner.pk)["legacy_over_limit"])
        p = PropertyListing.objects.first()
        p.title = "Edited legacy"
        p.save()
        with self.assertRaises(PropertyListingLimitReached):
            self.live()


class ConcurrentPublicationTests(TransactionTestCase):
    def setUp(self):
        seed_catalogue()

    @skipUnlessDBFeature("has_select_for_update")
    def test_owner_lock_serializes_final_slot_and_addon_activation(self):
        owner = user("race@pricing.test")
        make_listing(owner, status="PUBLISHED")
        barrier = Barrier(2)

        def publish(index):
            connections.close_all()
            try:
                local_owner = User.objects.get(pk=owner.pk)
                p = make_listing(local_owner, title=f"Concurrent {index}")
                barrier.wait(timeout=15)
                p.status = "PUBLISHED"
                try:
                    p.save()
                    return "published"
                except PropertyListingLimitReached:
                    return "limited"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, range(2)))
        self.assertCountEqual(results, ["published", "limited"])
        self.assertEqual(summary(owner.pk)["active_listing_count"], 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_agents_cannot_double_activate_one_shared_extra_unit(self):
        owner = user("agency-race@pricing.test")
        staff = user("race-staff@pricing.test", is_staff=True)
        other = user("second-race@pricing.test")
        agency = Agency.objects.create(name="Race Agency", slug="race-agency")
        for u in (owner, other):
            AgentProfile.objects.create(user=u, agency=agency)
        for _ in range(5):
            make_listing(owner, agency=agency, status="PUBLISHED")
        grant_package(
            PropertyAddOnPackage.objects.get(pk="SINGLE_EXTRA"), actor=staff, reason="Race test", agency=agency
        )
        barrier = Barrier(2)

        def publish(pk):
            connections.close_all()
            try:
                p = make_listing(User.objects.get(pk=pk), agency=Agency.objects.get(pk=agency.pk))
                barrier.wait(timeout=15)
                p.status = "PUBLISHED"
                try:
                    p.save()
                    return "published"
                except PropertyListingLimitReached:
                    return "limited"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, [owner.pk, other.pk]))
        self.assertCountEqual(results, ["published", "limited"])
        self.assertEqual(summary(agency_id=agency.pk)["active_listing_count"], 6)
        self.assertEqual(PropertyListingAddOn.objects.filter(status="ACTIVE").count(), 1)
