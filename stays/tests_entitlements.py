from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient
from accounts.models import User
from agencies.models import Agency, AgentProfile
from bookings.models import Booking, BookingStatus
from bookings.services import create_booking, transition, inventory, expire_pending
from messaging.models import Conversation
from notifications.models import Notification, NotificationPreference
from .models import (
    Stay,
    RoomType,
    RoomAvailability,
    StaySubscription,
    StayAddOnPackage,
    StayListingAddOn,
    StayCapacityReview,
)
from .entitlements import summary, grant_package, allocate_renewal, StayListingLimitReached
from .pricing_admin import StayListingAddOnAdmin, StaySubscriptionAdmin
from .services import submit, room_availability
from .tasks import process_stay_entitlements


def make_user(email, **kwargs):
    return User.objects.create_user(email=email, first_name="Stay", last_name="Test", is_email_verified=True, **kwargs)


def make_stay(owner, **kwargs):
    data = {
        "name": "Test Lodge",
        "description": "A guest lodge with rooms and mountain views.",
        "stay_type": "LODGE",
        "region": "Hhohho",
        "town": "Mbabane",
        "location": {"latitude": -26.3, "longitude": 31.1},
    }
    data.update(kwargs)
    return Stay.objects.create(owner=owner, **data)


def make_room(stay, **kwargs):
    return RoomType.objects.create(
        stay=stay,
        name="Guest Room",
        capacity_adults=2,
        total_capacity=2,
        quantity=kwargs.pop("quantity", 3),
        base_price=kwargs.pop("base_price", "500"),
        **kwargs,
    )


def seed_catalogues():
    for module in (
        "properties.migrations.0008_property_pricing_catalogue",
        "stays.migrations.0009_stay_pricing_catalogue",
    ):
        import_module(module).seed(apps, SimpleNamespace(connection=connection))


class StayEntitlementTests(TestCase):
    def setUp(self):
        self.host = make_user("host@entitlements.test")
        self.other = make_user("other@entitlements.test")
        self.guest = make_user("guest@entitlements.test")
        self.staff = make_user("staff@entitlements.test", is_staff=True, is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(self.host)

    def live(self, **kwargs):
        return make_stay(kwargs.pop("owner", self.host), status="PUBLISHED", **kwargs)

    def package(self, code="SINGLE_STAY_EXTRA", **kwargs):
        return grant_package(
            StayAddOnPackage.objects.get(pk=code),
            actor=kwargs.pop("actor", self.staff),
            reason="Documented staff grant",
            account=kwargs.pop("account", self.host),
            **kwargs,
        )

    def subscribe(self, code="HOST_PRO", **kwargs):
        return StaySubscription.objects.create(
            account=kwargs.pop("account", self.host),
            plan_id=code,
            granted_by=self.staff,
            grant_reason="Documented plan grant",
            starts_at=kwargs.pop("starts_at", timezone.now()),
            expires_at=kwargs.pop("expires_at", timezone.now() + timedelta(days=30)),
            **kwargs,
        )

    def extra(self, age=91):
        self.live()
        self.live()
        self.package()
        with patch("stays.entitlements.timezone.now", return_value=timezone.now() - timedelta(days=age)):
            stay = self.live()
        room = make_room(stay)
        return stay, room

    def book(self, stay, room, *, start=None, confirmed=True, guest=None):
        start = start or timezone.localdate() + timedelta(days=10)
        guest = guest or self.guest
        booking = create_booking(
            guest=guest,
            stay=stay,
            room_type=room,
            check_in=start,
            check_out=start + timedelta(days=2),
            adults=1,
            children=0,
            rooms=1,
            guest_name="Guest",
            guest_email=guest.email,
        )
        return transition(booking, BookingStatus.CONFIRMED, self.host) if confirmed else booking

    def test_free_two_stays_and_third_rejected_with_typed_counts(self):
        self.live()
        self.live()
        with self.assertRaises(StayListingLimitReached) as error:
            self.live()
        self.assertEqual(error.exception.detail["active_stays"], 2)
        self.assertEqual(error.exception.detail["listing_limit"], 2)
        self.assertIs(error.exception.detail["upgrade_available"], True)
        self.assertEqual(summary(self.host.pk)["remaining_publication_capacity"], 0)

    def test_drafts_at_capacity_and_submission_error_preserves_data(self):
        self.live()
        self.live()
        for _ in range(8):
            make_stay(self.host)
        response = self.client.post("/api/v1/stays/", {"name": "Saved lodge", "stay_type": "LODGE"}, format="json")
        self.assertEqual(response.status_code, 201)
        stay = make_stay(self.host)
        room = make_room(stay)
        response = self.client.post(f"/api/v1/stays/{stay.pk}/submit/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "STAY_LISTING_LIMIT_REACHED")
        self.assertIsInstance(response.data["active_stays"], int)
        stay.refresh_from_db()
        room.refresh_from_db()
        self.assertEqual(stay.status, "DRAFT")
        self.assertEqual(room.quantity, 3)

    def test_room_types_units_and_sold_out_dates_do_not_change_listing_capacity(self):
        stay = self.live()
        for i in range(9):
            make_room(stay, quantity=20, slug=f"room-{i}")
        room = stay.room_types.first()
        today = timezone.localdate()
        RoomAvailability.objects.create(room_type=room, date=today, available_units=0, is_blocked=True)
        self.assertFalse(room_availability(room, today, today + timedelta(days=1), 1, 0, 1)["available"])
        self.assertEqual(summary(self.host.pk)["active_stay_count"], 1)
        self.assertEqual(summary(self.host.pk)["base_slots_remaining"], 1)

    def test_non_public_states_excluded_and_published_edits_allowed_at_capacity(self):
        for status in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "PAUSED", "REJECTED", "SUSPENDED"]:
            make_stay(self.host, status=status)
        p = self.live()
        self.live()
        response = self.client.patch(
            f"/api/v1/stays/{p.pk}/", {"description": "Updated published lodge"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(summary(self.host.pk)["active_stay_count"], 2)

    def test_all_paid_plan_capacities_replace_free(self):
        for index, (code, allowance) in enumerate([("HOST_PRO", 5), ("BUSINESS", 15), ("ENTERPRISE", 30)]):
            owner = make_user(f"paid-{index}@entitlements.test")
            self.subscribe(code, account=owner)
            for _ in range(allowance):
                self.live(owner=owner)
            self.assertEqual(summary(owner.pk)["base_listing_allowance"], allowance)
            with self.assertRaises(StayListingLimitReached):
                self.live(owner=owner)

    def test_grant_permissions_reason_and_scope_constraints(self):
        with self.assertRaises(PermissionDenied):
            self.package(actor=self.host)
        unprivileged_staff = make_user("unprivileged@entitlements.test", is_staff=True)
        with self.assertRaises(PermissionDenied):
            self.package(actor=unprivileged_staff)
        agency = Agency.objects.create(name="Company", slug="company")
        with self.assertRaises(ModelValidationError):
            self.subscribe(agency=agency)
        with self.assertRaises(ModelValidationError):
            self.subscribe(auto_renew=True)
        with self.assertRaises(ModelValidationError):
            StaySubscription.objects.create(
                account=self.host,
                plan_id="HOST_PRO",
                granted_by=self.host,
                grant_reason="Forged",
                expires_at=timezone.now() + timedelta(days=30),
            )

    def test_company_quota_shared_and_personal_quota_separate(self):
        agency = Agency.objects.create(name="Hospitality team", slug="hospitality")
        for owner in (self.host, self.other):
            AgentProfile.objects.create(user=owner, agency=agency)
        self.live(agency=agency)
        self.live(owner=self.other, agency=agency)
        with self.assertRaises(StayListingLimitReached):
            self.live(agency=agency)
        self.live()
        self.live()
        self.assertEqual(summary(agency_id=agency.pk)["active_stay_count"], 2)
        self.assertEqual(summary(self.host.pk)["active_stay_count"], 2)

    def test_bundle_each_unit_activates_independently_and_sum_is_exact(self):
        units = self.package("TRIPLE_STAY_EXTRA")
        self.assertEqual(sum(unit.amount for unit in units), Decimal("199"))
        self.assertEqual(len({unit.pk for unit in units}), 3)
        self.assertTrue(all(unit.activated_at is None and unit.expires_at is None for unit in units))
        self.live()
        self.live()
        p = self.live()
        p.name = "Edited extra"
        p.save()
        self.assertEqual(StayListingAddOn.objects.filter(status="ACTIVE").count(), 1)
        unit = StayListingAddOn.objects.get(status="ACTIVE")
        self.assertEqual(unit.expires_at - unit.activated_at, timedelta(days=90))
        self.assertEqual(summary(self.host.pk)["unused_extra_allowances"], 2)
        same = self.package("TRIPLE_STAY_EXTRA", reference=unit.purchase_reference)
        self.assertEqual({u.pk for u in same}, {u.pk for u in units})

    def test_no_cross_account_units_forged_payment_or_public_grant(self):
        self.live()
        self.live()
        self.package(account=self.other)
        with self.assertRaises(StayListingLimitReached):
            self.live()
        other_stay = make_stay(self.other)
        self.assertEqual(self.client.get(f"/api/v1/account/stay-entitlements/?stay={other_stay.pk}").status_code, 403)
        self.assertEqual(
            self.client.patch(f"/api/v1/stays/{other_stay.pk}/", {"name": "Stolen"}, format="json").status_code, 403
        )
        for path in ["/api/v1/account/stay-entitlements/", "/api/v1/pricing/stays/"]:
            self.assertEqual(
                self.client.post(path, {"plan": "ENTERPRISE", "payment_success": True}, format="json").status_code, 405
            )
        draft = make_stay(self.host)
        self.assertEqual(
            self.client.patch(
                f"/api/v1/stays/{draft.pk}/", {"status": "PUBLISHED", "plan": "ENTERPRISE", "paid": True}, format="json"
            ).status_code,
            200,
        )
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT")

    def test_assigned_unit_cannot_cover_another_stay_or_cross_account(self):
        self.live()
        self.live()
        self.package()
        p = self.live()
        p.status = "PAUSED"
        p.save()
        with self.assertRaises(StayListingLimitReached):
            self.live()
        self.assertTrue(summary(self.host.pk, stay_id=p.pk)["can_publish_stay"])
        p.status = "PUBLISHED"
        p.save()
        unit = StayListingAddOn.objects.get(status="ACTIVE")
        unit.assigned_stay = make_stay(self.other)
        with self.assertRaises(ModelValidationError):
            unit.save()

    def test_expiry_without_obligations_pauses_only_extra_preserving_room_data(self):
        stay, room = self.extra()
        date = timezone.localdate() + timedelta(days=1)
        calendar = RoomAvailability.objects.create(room_type=room, date=date, available_units=2, custom_price="600")
        room.refresh_from_db()
        calendar.refresh_from_db()
        before = (room.pk, room.quantity, room.base_price, calendar.pk, calendar.available_units, calendar.custom_price)
        self.assertEqual(process_stay_entitlements(), 1)
        self.assertEqual(process_stay_entitlements(), 0)
        stay.refresh_from_db()
        room.refresh_from_db()
        calendar.refresh_from_db()
        self.assertEqual(stay.status, "PAUSED")
        self.assertEqual(
            (room.pk, room.quantity, room.base_price, calendar.pk, calendar.available_units, calendar.custom_price),
            before,
        )
        self.assertEqual(Stay.objects.filter(status="PUBLISHED").count(), 2)

    def test_expired_extra_uses_free_ordinary_capacity(self):
        stay, _ = self.extra()
        ordinary = Stay.objects.exclude(pk=stay.pk).first()
        ordinary.status = "PAUSED"
        ordinary.save()
        process_stay_entitlements()
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PUBLISHED")
        self.assertFalse(summary(self.host.pk)["legacy_over_limit"])

    def test_confirmed_future_booking_price_inventory_conversation_survive_expiry(self):
        stay, room = self.extra()
        booking = self.book(stay, room)
        before = deepcopy({field.name: getattr(booking, field.attname) for field in Booking._meta.fields})
        day = booking.check_in
        before_inventory = inventory(room, day)
        process_stay_entitlements()
        booking.refresh_from_db()
        stay.refresh_from_db()
        room.refresh_from_db()
        self.assertEqual({field.name: getattr(booking, field.attname) for field in Booking._meta.fields}, before)
        self.assertEqual(inventory(room, day), before_inventory)
        self.assertEqual(stay.status, "PUBLISHED")
        self.assertEqual(StayCapacityReview.objects.get(stay=stay).status, "PROTECTED_BOOKINGS")
        self.assertTrue(summary(self.host.pk)["protected_booking_over_limit"])
        self.assertTrue(Conversation.objects.filter(pk=booking.conversation_id).exists())
        self.client.force_authenticate(self.guest)
        self.assertEqual(self.client.get(f"/api/v1/stays/{stay.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/bookings/{booking.pk}/").status_code, 200)
        # Protection does not introduce a new booking-blocking policy.
        new_guest = make_user("next-guest@entitlements.test")
        next_booking = self.book(stay, room, confirmed=False, guest=new_guest)
        self.assertEqual(next_booking.status, "PENDING")

    def test_current_confirmed_stay_is_protected_until_completed(self):
        stay, room = self.extra()
        booking = self.book(stay, room, start=timezone.localdate())
        process_stay_entitlements()
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PUBLISHED")
        with patch("stays.tasks.timezone.now", return_value=timezone.now() + timedelta(days=2)):
            booking = transition(booking, BookingStatus.COMPLETED, self.host)
            process_stay_entitlements()
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PAUSED")
        self.assertEqual(booking.status, "COMPLETED")

    def test_pending_hold_is_protected_and_keeps_existing_expiry_lifecycle(self):
        stay, room = self.extra()
        booking = self.book(stay, room, confirmed=False)
        expires = booking.expires_at
        process_stay_entitlements()
        stay.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(stay.status, "PUBLISHED")
        self.assertEqual(booking.status, "PENDING")
        self.assertEqual(booking.expires_at, expires)
        with patch("stays.tasks.timezone.now", return_value=expires + timedelta(seconds=1)):
            self.assertEqual(expire_pending(), 1)
            process_stay_entitlements()
        stay.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(stay.status, "PAUSED")
        self.assertEqual(booking.status, "EXPIRED")
        self.assertEqual(booking.expires_at, expires)

    def test_existing_cancellation_semantics_release_inventory_then_safe_pause(self):
        stay, room = self.extra()
        booking = self.book(stay, room)
        process_stay_entitlements()
        transition(booking, BookingStatus.CANCELLED, self.guest)
        self.assertEqual(inventory(room, booking.check_in), room.quantity)
        process_stay_entitlements()
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PAUSED")
        self.assertTrue(Booking.objects.filter(pk=booking.pk, status="CANCELLED").exists())

    def test_admin_renewal_protected_stay_retains_old_grant_and_reservations(self):
        stay, room = self.extra()
        booking = self.book(stay, room)
        process_stay_entitlements()
        old = StayListingAddOn.objects.get()
        old_expiry = old.expires_at
        self.package()
        renewed = allocate_renewal(stay, actor=self.staff)
        self.assertEqual(allocate_renewal(stay, actor=self.staff).pk, renewed.pk)
        self.assertEqual(StayListingAddOn.objects.count(), 2)
        old.refresh_from_db()
        self.assertEqual(old.expires_at, old_expiry)
        self.assertEqual(old.status, "EXPIRED")
        process_stay_entitlements()
        stay.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(stay.status, "PUBLISHED")
        self.assertEqual(booking.status, "CONFIRMED")
        self.assertEqual(StayCapacityReview.objects.get(stay=stay).status, "RESOLVED")

    def test_resubmit_paused_extra_after_new_grant(self):
        stay, _ = self.extra()
        process_stay_entitlements()
        stay.refresh_from_db()
        self.package()
        submit(stay)
        self.assertEqual(stay.status, "SUBMITTED")
        stay.status = "PUBLISHED"
        stay.save()
        self.assertEqual(StayListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    def test_subscription_grace_and_expiry_preserve_all_inventory_and_bookings(self):
        sub = self.subscribe()
        stays = [self.live() for _ in range(5)]
        stay = stays[-1]
        room = make_room(stay)
        booking = self.book(stay, room, start=timezone.localdate() + timedelta(days=45))
        with self.captureOnCommitCallbacks(execute=True):
            with patch("stays.tasks.timezone.now", return_value=sub.expires_at + timedelta(days=1)):
                process_stay_entitlements()
                process_stay_entitlements()
                self.assertEqual(summary(self.host.pk)["base_listing_allowance"], 5)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "GRACE")
        self.assertIsNotNone(sub.grace_entered_at)
        self.assertEqual(Notification.objects.filter(event_key__contains=":grace:").count(), 1)
        with patch("stays.tasks.timezone.now", return_value=sub.grace_until + timedelta(seconds=1)):
            process_stay_entitlements()
            usage = summary(self.host.pk)
            self.assertEqual(usage["base_listing_allowance"], 2)
            self.assertEqual(usage["remaining_publication_capacity"], 0)
            with self.assertRaises(StayListingLimitReached):
                self.live()
        sub.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(sub.status, "EXPIRED")
        self.assertIsNotNone(sub.expired_at)
        self.assertEqual(Stay.objects.filter(status="PUBLISHED").count(), 5)
        self.assertEqual(booking.status, "CONFIRMED")
        self.assertEqual(StayCapacityReview.objects.get(stay=stay).status, "PROTECTED_BOOKINGS")

    def test_cancelled_subscription_downgrade_and_immutable_history(self):
        sub = self.subscribe()
        [self.live() for _ in range(4)]
        sub.status = "CANCELLED"
        sub.save()
        process_stay_entitlements()
        self.assertTrue(summary(self.host.pk)["legacy_over_limit"])
        self.assertEqual(Stay.objects.filter(status="PUBLISHED").count(), 4)
        sub.expires_at += timedelta(days=30)
        with self.assertRaises(ModelValidationError):
            sub.save()

    def test_reminders_expiration_and_preferences_are_idempotent(self):
        stay, _ = self.extra(age=89)
        unit = StayListingAddOn.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            process_stay_entitlements()
            process_stay_entitlements()
        self.assertEqual(Notification.objects.filter(event_key__contains=":reminder-").count(), 2)
        with patch("stays.tasks.timezone.now", return_value=unit.expires_at + timedelta(seconds=1)):
            with self.captureOnCommitCallbacks(execute=True):
                process_stay_entitlements()
                process_stay_entitlements()
        self.assertEqual(Notification.objects.filter(event_key__contains=":expired:").count(), 1)
        NotificationPreference.objects.update_or_create(
            user=self.host, defaults={"in_app_enabled": False, "email_enabled": False}
        )
        before = Notification.objects.count()
        with self.captureOnCommitCallbacks(execute=True):
            process_stay_entitlements()
        self.assertEqual(Notification.objects.count(), before)

    def test_original_staff_demotion_does_not_break_expiration_of_audited_grants(self):
        stay, _ = self.extra()
        self.staff.is_staff = False
        self.staff.is_superuser = False
        self.staff.save()
        process_stay_entitlements()
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PAUSED")

    def test_api_catalogue_promotion_disabled_and_property_catalogue_unchanged(self):
        data = self.client.get("/api/v1/pricing/stays/").data
        self.assertEqual([p["price"] for p in data["plans"]], ["0.00", "199.00", "449.00", "899.00"])
        self.assertEqual([p["active_listing_limit"] for p in data["plans"]], [2, 5, 15, 30])
        self.assertEqual(data["promotions"][0]["price"], "59.00")
        self.assertFalse(data["promotions"][0]["operational"])
        self.assertFalse(data["checkout_available"])
        self.assertEqual(data["booking_commission_percent"], 0)
        prop = self.client.get("/api/v1/pricing/properties/").data
        self.assertEqual([p["active_listing_limit"] for p in prop["plans"]], [2, 5, 10, 25, 75])
        self.assertEqual([p["price"] for p in prop["plans"]], ["0.00", "0.00", "149.00", "349.00", "699.00"])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/account/stay-entitlements/").status_code, 401)

    def test_flag_does_not_enable_unverified_checkout(self):
        with override_settings(STAY_PURCHASES_ENABLED=True):
            self.assertFalse(self.client.get("/api/v1/pricing/stays/").data["checkout_available"])

    def test_approval_restore_admin_orm_and_bulk_cannot_bypass_quota(self):
        self.live()
        self.live()
        stay = make_stay(self.host, status="SUBMITTED")
        make_room(stay)
        self.client.force_authenticate(self.staff)
        for status, action in [("SUBMITTED", "approve"), ("SUSPENDED", "restore")]:
            stay.status = status
            stay.save()
            response = self.client.post(f"/api/v1/staff/stays/{stay.pk}/{action}/")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "STAY_LISTING_LIMIT_REACHED")
        stay.status = "PUBLISHED"
        with self.assertRaises(StayListingLimitReached):
            stay.save()
        with self.assertRaises(ModelValidationError):
            Stay.objects.filter(pk=stay.pk).update(status="PUBLISHED")
        with self.assertRaises(ModelValidationError):
            Stay.objects.bulk_update([stay], ["status"])
        with self.assertRaises(ModelValidationError):
            Stay.objects.bulk_create([stay])

    def test_ownership_transfer_checks_destination_capacity(self):
        self.live(owner=self.other)
        self.live(owner=self.other)
        stay = self.live()
        stay.owner = self.other
        with self.assertRaises(StayListingLimitReached):
            stay.save()
        stay.refresh_from_db()
        self.assertEqual(stay.owner_id, self.host.pk)

    def test_same_team_responsible_user_change_retains_the_existing_slot_and_unit(self):
        agency = Agency.objects.create(name="Shared host team", slug="shared-host-team")
        for owner in (self.host, self.other):
            AgentProfile.objects.create(user=owner, agency=agency)
        self.live(agency=agency); self.live(owner=self.other, agency=agency)
        self.package(account=None, agency=agency)
        stay = self.live(agency=agency)
        unit = StayListingAddOn.objects.get(status="ACTIVE")
        stay.owner = self.other; stay.full_clean(); stay.save()
        self.assertEqual(summary(agency_id=agency.pk)["active_stay_count"], 3)
        self.assertEqual(StayListingAddOn.objects.get(status="ACTIVE").pk, unit.pk)

    def test_stale_api_edit_cannot_undo_owner_transfer(self):
        from .serializers import StayWriteSerializer
        from rest_framework.exceptions import ValidationError
        stay = self.live(); stale = Stay.objects.get(pk=stay.pk)
        stay.owner = self.other; stay.save()
        serializer = StayWriteSerializer(context={"request": SimpleNamespace(user=self.host)})
        with self.assertRaises(ValidationError): serializer.update(stale, {"name": "Stale edit"})
        stay.refresh_from_db(); self.assertEqual(stay.owner_id, self.other.pk)

    def test_stale_api_edit_preserves_current_readonly_publication_state(self):
        from .serializers import StayWriteSerializer
        stay = self.live(); stale = Stay.objects.get(pk=stay.pk)
        stay.status = "PAUSED"; stay.save()
        serializer = StayWriteSerializer(context={"request": SimpleNamespace(user=self.host)})
        saved = serializer.update(stale, {"name": "Edited safely after moderation"})
        self.assertEqual(saved.status, "PAUSED")
        self.assertEqual(saved.name, "Edited safely after moderation")

    def test_admin_package_and_subscription_forms_record_staff_and_references(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        model_admin = StayListingAddOnAdmin(StayListingAddOn, admin.site)
        Form = model_admin.get_form(request)
        form = Form(
            data={
                "account": self.host.pk,
                "source_package": "TRIPLE_STAY_EXTRA",
                "grant_reason": "Offline grant",
                "provider": "offline",
                "transaction_reference": "STAY-123",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save(commit=False)
        model_admin.save_model(request, obj, form, False)
        self.assertEqual(
            StayListingAddOn.objects.filter(granted_by=self.staff, transaction_reference="STAY-123").count(), 3
        )
        Form = StaySubscriptionAdmin(StaySubscription, admin.site).get_form(request)
        form = Form(
            data={
                "account": self.host.pk,
                "plan": "HOST_PRO",
                "status": "ACTIVE",
                "grant_reason": "Plan grant",
                "starts_at_0": "2026-10-01",
                "starts_at_1": "12:00:00",
                "expires_at_0": "2026-11-01",
                "expires_at_1": "12:00:00",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.amount, Decimal("199"))
        self.assertEqual(form.instance.grace_until - form.instance.expires_at, timedelta(days=7))

    def test_database_constraints_enforce_ownership_and_single_purchase_unit(self):
        unit = self.package()[0]
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Deliberately bypass model validation to verify the database layer.
            StayListingAddOn.objects.filter(pk=unit.pk).update(account_id=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StayListingAddOn.objects.bulk_create(
                [
                    StayListingAddOn(
                        account=self.host,
                        source_package=unit.source_package,
                        granted_by=self.staff,
                        grant_reason="Duplicate",
                        purchase_reference=unit.purchase_reference,
                        unit_number=1,
                        amount=79,
                    )
                ]
            )

    def test_catalogue_migration_preserves_eight_existing_stays_and_booking_records(self):
        historical = (
            MigrationExecutor(connection)
            .loader.project_state([("stays", "0007_alter_stay_options_alter_stay_status")])
            .apps.get_model("stays", "Stay")
        )
        for index in range(8):
            historical.objects.create(
                owner_id=self.host.pk,
                public_id=f"OLD-{index}",
                slug=f"old-{index}",
                name="Existing lodge",
                stay_type="LODGE",
                status="PUBLISHED",
            )
        stay = Stay.objects.first()
        room = make_room(stay)
        booking = self.book(stay, room)
        snapshot = (
            stay.pk,
            room.pk,
            room.quantity,
            booking.pk,
            booking.reference,
            booking.nightly_pricing,
            booking.total,
        )
        seed_catalogues()
        process_stay_entitlements()
        stay.refresh_from_db()
        room.refresh_from_db()
        booking.refresh_from_db()
        self.assertEqual(Stay.objects.filter(status="PUBLISHED").count(), 8)
        self.assertEqual(
            (stay.pk, room.pk, room.quantity, booking.pk, booking.reference, booking.nightly_pricing, booking.total),
            snapshot,
        )
        self.assertTrue(summary(self.host.pk)["legacy_over_limit"])
        with self.assertRaises(StayListingLimitReached):
            self.live()


class StayConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_catalogues()
        self.host = make_user("race-host@entitlements.test")
        self.staff = make_user("race-staff@entitlements.test", is_staff=True, is_superuser=True)

    def race_publish(self, *, extra=False, same_stay=False):
        make_stay(self.host, status="PUBLISHED")
        if extra:
            make_stay(self.host, status="PUBLISHED")
            grant_package(
                StayAddOnPackage.objects.get(pk="SINGLE_STAY_EXTRA"),
                actor=self.staff,
                reason="Concurrency grant",
                account=self.host,
            )
        stays = [make_stay(self.host)]
        if not same_stay:
            stays.append(make_stay(self.host))
        barrier = Barrier(2)

        def publish(index):
            connections.close_all()
            try:
                stay = Stay.objects.get(pk=stays[0 if same_stay else index].pk)
                barrier.wait(timeout=15)
                stay.status = "PUBLISHED"
                try:
                    stay.save()
                    return "published"
                except StayListingLimitReached:
                    return "limited"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(publish, range(2)))

    @skipUnlessDBFeature("has_select_for_update")
    def test_final_base_slot_is_serialized(self):
        self.assertCountEqual(self.race_publish(), ["published", "limited"])
        self.assertEqual(summary(self.host.pk)["active_stay_count"], 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_single_extra_cannot_be_double_activated(self):
        self.assertCountEqual(self.race_publish(extra=True), ["published", "limited"])
        self.assertEqual(StayListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_duplicate_publication_same_stay_uses_one_unit(self):
        self.assertCountEqual(self.race_publish(extra=True, same_stay=True), ["published", "published"])
        self.assertEqual(StayListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_two_team_agents_share_one_extra_stay_unit_under_concurrency(self):
        other = make_user("team-race@entitlements.test")
        agency = Agency.objects.create(name="Concurrent hospitality", slug="concurrent-hospitality")
        for owner in (self.host, other): AgentProfile.objects.create(user=owner, agency=agency)
        make_stay(self.host, agency=agency, status="PUBLISHED")
        make_stay(other, agency=agency, status="PUBLISHED")
        grant_package(StayAddOnPackage.objects.get(pk="SINGLE_STAY_EXTRA"), actor=self.staff, reason="Team race grant", agency=agency)
        ids = [make_stay(owner, agency=agency).pk for owner in (self.host, other)]
        barrier = Barrier(2)
        def publish(pk):
            connections.close_all()
            try:
                stay = Stay.objects.get(pk=pk); barrier.wait(timeout=15); stay.status = "PUBLISHED"
                try: stay.save(); return "published"
                except StayListingLimitReached: return "limited"
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, ids))
        self.assertCountEqual(results, ["published", "limited"])
        self.assertEqual(summary(agency_id=agency.pk)["active_stay_count"], 3)
        self.assertEqual(StayListingAddOn.objects.filter(status="ACTIVE").count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_booking_creation_and_expiry_cannot_invalidate_committed_reservation(self):
        make_stay(self.host, status="PUBLISHED")
        make_stay(self.host, status="PUBLISHED")
        grant_package(
            StayAddOnPackage.objects.get(pk="SINGLE_STAY_EXTRA"),
            actor=self.staff,
            reason="Booking race",
            account=self.host,
        )
        with patch("stays.entitlements.timezone.now", return_value=timezone.now() - timedelta(days=91)):
            stay = make_stay(self.host, status="PUBLISHED")
        room = make_room(stay)
        guest = make_user("race-guest@entitlements.test")
        booking_locked = Event()
        expiry_owner_locked = Event()
        from bookings.services import create_conversation as original_conversation
        from stays.tasks import resolve_expired_stay as original_resolve

        def gated_conversation(*args, **kwargs):
            booking_locked.set()
            self.assertTrue(expiry_owner_locked.wait(timeout=15))
            return original_conversation(*args, **kwargs)

        def gated_expiry(unit, now):
            expiry_owner_locked.set()
            return original_resolve(unit, now)

        def reserve():
            connections.close_all()
            try:
                booking = create_booking(
                    guest=User.objects.get(pk=guest.pk),
                    stay=Stay.objects.get(pk=stay.pk),
                    room_type=RoomType.objects.get(pk=room.pk),
                    check_in=timezone.localdate() + timedelta(days=10),
                    check_out=timezone.localdate() + timedelta(days=11),
                    adults=1,
                    children=0,
                    rooms=1,
                    guest_name="Race Guest",
                    guest_email=guest.email,
                )
                return booking.pk
            finally:
                connections.close_all()

        def expire():
            connections.close_all()
            try:
                self.assertTrue(booking_locked.wait(timeout=15))
                return process_stay_entitlements()
            finally:
                connections.close_all()

        with patch("bookings.services.create_conversation", side_effect=gated_conversation), patch(
            "stays.tasks.resolve_expired_stay", side_effect=gated_expiry
        ), ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(reserve)
            expiring = pool.submit(expire)
            booking_id = pending.result(timeout=30)
            expiring.result(timeout=30)
        stay.refresh_from_db()
        self.assertEqual(stay.status, "PUBLISHED")
        self.assertEqual(Booking.objects.get(pk=booking_id).status, "PENDING")
        self.assertEqual(StayCapacityReview.objects.get(stay=stay).status, "PROTECTED_BOOKINGS")
