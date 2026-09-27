from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("verification", "0004_verification_changes_requested")]

    operations = [
        migrations.AddField(
            model_name="verificationrequest",
            name="requirement_notes",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
