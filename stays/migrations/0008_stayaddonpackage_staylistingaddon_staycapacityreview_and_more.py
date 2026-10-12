import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agencies", "0004_agency_onboarding"),
        ("stays", "0007_alter_stay_options_alter_stay_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StayAddOnPackage",
            fields=[
                ("code", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=80)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("quantity", models.PositiveIntegerField()),
                ("duration_days", models.PositiveIntegerField(default=90)),
                ("purchase_validity_days", models.PositiveIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["display_order", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("price__gte", 0)), name="stay_package_price_nonnegative"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("duration_days__gt", 0), ("quantity__gt", 0)),
                        name="stay_package_positive_units",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StayListingAddOn",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("grant_reason", models.TextField()),
                ("granted_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("provider", models.CharField(blank=True, max_length=80)),
                ("transaction_reference", models.CharField(blank=True, max_length=160)),
                ("purchase_reference", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("unit_number", models.PositiveIntegerField(default=1)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("duration_days", models.PositiveIntegerField(default=90)),
                ("activate_before", models.DateTimeField(blank=True, null=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("expiry_processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("UNUSED", "Unused"), ("ACTIVE", "Active"), ("EXPIRED", "Expired")],
                        default="UNUSED",
                        max_length=12,
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="agencies.agency",
                    ),
                ),
                (
                    "assigned_stay",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="listing_addons",
                        to="stays.stay",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "source_package",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="stays.stayaddonpackage"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="StayCapacityReview",
            fields=[
                (
                    "stay",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="capacity_review",
                        serialize=False,
                        to="stays.stay",
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("ADDON_EXPIRED", "Add-on expired"),
                            ("SUBSCRIPTION_EXPIRED", "Subscription expired or cancelled"),
                            ("LEGACY_OVER_LIMIT", "Legacy over limit"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PROTECTED_BOOKINGS", "Protected bookings"),
                            ("OVER_LIMIT", "Over limit"),
                            ("RESOLVED", "Resolved"),
                        ],
                        max_length=24,
                    ),
                ),
                ("pause_when_safe", models.BooleanField(default=False)),
                ("opened_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_checked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "expired_addon",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="stays.staylistingaddon"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="StayPlan",
            fields=[
                ("code", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=80)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "billing_interval",
                    models.CharField(choices=[("FOREVER", "Forever"), ("MONTH", "Month")], max_length=12),
                ),
                ("active_listing_limit", models.PositiveIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["display_order", "code"],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("price__gte", 0)), name="stay_plan_price_nonnegative")
                ],
            },
        ),
        migrations.CreateModel(
            name="StayPromotion",
            fields=[
                ("code", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("display_name", models.CharField(max_length=80)),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("duration_days", models.PositiveIntegerField(default=7)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("duration_days__gt", 0), ("price__gte", 0)),
                        name="stay_promotion_positive_values",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="StaySubscription",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("grant_reason", models.TextField()),
                ("granted_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("provider", models.CharField(blank=True, max_length=80)),
                ("transaction_reference", models.CharField(blank=True, max_length=160)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ACTIVE", "Active"),
                            ("GRACE", "Grace"),
                            ("EXPIRED", "Expired"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        default="ACTIVE",
                        max_length=12,
                    ),
                ),
                ("starts_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("grace_until", models.DateTimeField(blank=True)),
                ("grace_entered_at", models.DateTimeField(blank=True, null=True)),
                ("expired_at", models.DateTimeField(blank=True, null=True)),
                ("auto_renew", models.BooleanField(default=False)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="agencies.agency",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                ("plan", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="stays.stayplan")),
            ],
        ),
        migrations.AddConstraint(
            model_name="staylistingaddon",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("account__isnull", False), ("agency__isnull", True)),
                    models.Q(("account__isnull", True), ("agency__isnull", False)),
                    _connector="OR",
                ),
                name="stay_addon_exactly_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="staylistingaddon",
            constraint=models.UniqueConstraint(
                fields=("purchase_reference", "unit_number"), name="unique_stay_addon_purchase_unit"
            ),
        ),
        migrations.AddConstraint(
            model_name="staylistingaddon",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "ACTIVE")), fields=("assigned_stay",), name="one_active_addon_per_stay"
            ),
        ),
        migrations.AddConstraint(
            model_name="staylistingaddon",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gte", 0), ("duration_days__gt", 0), ("unit_number__gt", 0)),
                name="stay_addon_positive_values",
            ),
        ),
        migrations.AddConstraint(
            model_name="staylistingaddon",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("activated_at__isnull", True),
                        ("assigned_stay__isnull", True),
                        ("expires_at__isnull", True),
                        ("status", "UNUSED"),
                    ),
                    models.Q(
                        ("activated_at__isnull", False),
                        ("assigned_stay__isnull", False),
                        ("expires_at__gt", models.F("activated_at")),
                        ("status__in", ["ACTIVE", "EXPIRED"]),
                    ),
                    _connector="OR",
                ),
                name="stay_addon_activation_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="staycapacityreview",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("resolved_at__isnull", False), ("status", "RESOLVED")),
                    models.Q(("resolved_at__isnull", True), ("status__in", ["PROTECTED_BOOKINGS", "OVER_LIMIT"])),
                    _connector="OR",
                ),
                name="stay_review_resolution_date",
            ),
        ),
        migrations.AddConstraint(
            model_name="staysubscription",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("account__isnull", False), ("agency__isnull", True)),
                    models.Q(("account__isnull", True), ("agency__isnull", False)),
                    _connector="OR",
                ),
                name="stay_subscription_exactly_one_owner",
            ),
        ),
        migrations.AddConstraint(
            model_name="staysubscription",
            constraint=models.UniqueConstraint(
                condition=models.Q(("account__isnull", False), ("status__in", ["ACTIVE", "GRACE"])),
                fields=("account",),
                name="one_stay_subscription_account",
            ),
        ),
        migrations.AddConstraint(
            model_name="staysubscription",
            constraint=models.UniqueConstraint(
                condition=models.Q(("agency__isnull", False), ("status__in", ["ACTIVE", "GRACE"])),
                fields=("agency",),
                name="one_stay_subscription_agency",
            ),
        ),
        migrations.AddConstraint(
            model_name="staysubscription",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("amount__gte", 0),
                    ("expires_at__gt", models.F("starts_at")),
                    ("grace_until__gte", models.F("expires_at")),
                ),
                name="stay_subscription_valid_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="staysubscription",
            constraint=models.CheckConstraint(
                condition=models.Q(("auto_renew", False)), name="stay_subscription_no_auto_renewal"
            ),
        ),
    ]
