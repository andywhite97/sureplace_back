from django.db import migrations
ITEMS=("Wi-Fi","Breakfast","Restaurant","Swimming Pool","Parking","Air Conditioning","Airport Transfer","Bar","Spa","Gym","Conference Facilities","Room Service","Laundry","Backup Power","Family Friendly","Wheelchair Accessible")
def seed(apps,schema_editor):
    Model=apps.get_model("stays","StayAmenity")
    from django.utils.text import slugify
    for name in ITEMS: Model.objects.get_or_create(slug=slugify(name),defaults={"name":name})
class Migration(migrations.Migration):
    dependencies=[("stays","0001_initial")]; operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
