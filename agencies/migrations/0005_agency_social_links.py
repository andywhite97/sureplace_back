from django.db import migrations, models
import core.social_links


class Migration(migrations.Migration):
    dependencies = [("agencies", "0004_agency_onboarding")]

    operations = [
        migrations.AddField(
            model_name="agency",
            name="facebook_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_facebook_url]),
        ),
        migrations.AddField(
            model_name="agency",
            name="instagram_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_instagram_url]),
        ),
        migrations.AddField(
            model_name="agency",
            name="tiktok_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_tiktok_url]),
        ),
    ]
