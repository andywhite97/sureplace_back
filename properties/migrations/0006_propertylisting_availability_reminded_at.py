from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("properties", "0005_propertylisting_staff_moderation")]
    operations = [
        migrations.AddField(
            model_name="propertylisting",
            name="availability_reminded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
