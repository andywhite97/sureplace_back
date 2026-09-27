import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_email_verification_timestamps")]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "ordering": ["-date_joined"],
                "permissions": [("moderate_user", "Can restrict and reinstate user accounts")],
            },
        ),
        migrations.CreateModel(
            name="UserModerationEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("RESTRICTED", "Restricted"), ("REINSTATED", "Reinstated")], max_length=16)),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(null=True, on_delete=models.SET_NULL, related_name="account_moderation_actions", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=models.CASCADE, related_name="moderation_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="usermoderationevent",
            index=models.Index(fields=["user", "-created_at"], name="accounts_us_user_id_d31cf8_idx"),
        ),
    ]
