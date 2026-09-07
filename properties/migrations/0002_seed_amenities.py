from django.db import migrations


AMENITIES = (
    ("Swimming Pool", "swimming-pool", "Leisure"),
    ("Garden", "garden", "Outdoor"),
    ("Wi-Fi", "wi-fi", "Connectivity"),
    ("Security", "security", "Security"),
    ("Furnished", "furnished", "Interior"),
    ("Air Conditioning", "air-conditioning", "Interior"),
    ("Pet Friendly", "pet-friendly", "Policy"),
    ("Backup Power", "backup-power", "Utilities"),
    ("Wheelchair Accessible", "wheelchair-accessible", "Accessibility"),
    ("Fenced", "fenced", "Security"),
    ("CCTV", "cctv", "Security"),
    ("Borehole", "borehole", "Utilities"),
)


def seed_amenities(apps, schema_editor):
    Amenity = apps.get_model("properties", "Amenity")
    for name, slug, category in AMENITIES:
        Amenity.objects.get_or_create(slug=slug, defaults={"name": name, "category": category})


def remove_seeded_amenities(apps, schema_editor):
    Amenity = apps.get_model("properties", "Amenity")
    Amenity.objects.filter(slug__in=[item[1] for item in AMENITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("properties", "0001_initial")]
    operations = [migrations.RunPython(seed_amenities, remove_seeded_amenities)]
