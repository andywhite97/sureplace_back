from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("verification", "0003_verificationrequest_verificatio_status_b771d1_idx")]
    operations = [
        migrations.AlterField(
            model_name="verificationrequest",
            name="status",
            field=models.CharField(
                choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"),
                         ("UNDER_REVIEW", "Under review"), ("APPROVED", "Approved"),
                         ("REJECTED", "Rejected"), ("CHANGES_REQUESTED", "Changes requested"),
                         ("CANCELLED", "Cancelled"), ("EXPIRED", "Expired")],
                default="DRAFT", max_length=20,
            ),
        ),
    ]
