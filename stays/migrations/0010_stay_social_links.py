from django.db import migrations, models
import core.social_links


class Migration(migrations.Migration):
    dependencies = [("stays", "0009_stay_pricing_catalogue")]

    operations = [
        migrations.AddField(
            model_name="stay",
            name="facebook_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_facebook_url]),
        ),
        migrations.AddField(
            model_name="stay",
            name="instagram_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_instagram_url]),
        ),
        migrations.AddField(
            model_name="stay",
            name="tiktok_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_tiktok_url]),
        ),
    ]
