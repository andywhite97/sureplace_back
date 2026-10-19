from django.db import migrations, models
import core.social_links


class Migration(migrations.Migration):
    dependencies = [("properties", "0008_property_pricing_catalogue")]

    operations = [
        migrations.AddField(
            model_name="propertylisting",
            name="facebook_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_facebook_url]),
        ),
        migrations.AddField(
            model_name="propertylisting",
            name="instagram_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_instagram_url]),
        ),
        migrations.AddField(
            model_name="propertylisting",
            name="tiktok_url",
            field=models.URLField(blank=True, validators=[core.social_links.validate_tiktok_url]),
        ),
    ]
