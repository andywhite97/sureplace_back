import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("agencies", "0003_agency_country_code"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="agency",
            name="suburb",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="agency",
            name="trading_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="agentprofile",
            name="role",
            field=models.CharField(
                choices=[("OWNER", "Owner"), ("ADMIN", "Admin"), ("AGENT", "Agent")],
                default="AGENT",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="AgencyInvitation",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(max_length=254)),
                (
                    "role",
                    models.CharField(
                        choices=[("OWNER", "Owner"), ("ADMIN", "Admin"), ("AGENT", "Agent")],
                        default="AGENT",
                        max_length=16,
                    ),
                ),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("ACCEPTED", "Accepted"),
                            ("DECLINED", "Declined"),
                            ("EXPIRED", "Expired"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("expires_at", models.DateTimeField()),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("declined_at", models.DateTimeField(blank=True, null=True)),
                (
                    "accepted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agency_invitations_accepted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invitations",
                        to="agencies.agency",
                    ),
                ),
                (
                    "inviter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agency_invitations_sent",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="agencyinvitation",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="PENDING"),
                fields=("agency", "email", "status"),
                name="unique_pending_agency_invitation",
            ),
        ),
    ]
