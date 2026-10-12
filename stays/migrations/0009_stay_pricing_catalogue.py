from decimal import Decimal
from django.db import migrations


def seed(apps, schema_editor):
    Plan = apps.get_model("stays", "StayPlan")
    Package = apps.get_model("stays", "StayAddOnPackage")
    Promotion = apps.get_model("stays", "StayPromotion")
    alias = schema_editor.connection.alias
    for order, (code, name, price, allowance) in enumerate([
        ("HOST_FREE", "Host Free", "0", 2), ("HOST_PRO", "Host Pro", "199", 5),
        ("BUSINESS", "Business", "449", 15), ("ENTERPRISE", "Enterprise", "899", 30),
    ]):
        Plan.objects.using(alias).get_or_create(code=code, defaults={"display_name": name, "price": Decimal(price), "active_listing_limit": allowance, "billing_interval": "FOREVER" if price == "0" else "MONTH", "display_order": order})
    for order, (code, name, price, quantity) in enumerate([
        ("SINGLE_STAY_EXTRA", "1 Extra Stay", "79", 1), ("TRIPLE_STAY_EXTRA", "3 Extra Stays", "199", 3),
    ]):
        Package.objects.using(alias).get_or_create(code=code, defaults={"display_name": name, "price": Decimal(price), "quantity": quantity, "duration_days": 90, "display_order": order})
    Promotion.objects.using(alias).get_or_create(code="STAY_BOOST_7D", defaults={"display_name": "7-Day Stay Boost", "price": Decimal("59"), "duration_days": 7})
    # No existing Stay, RoomType, RoomAvailability or Booking record is written.


class Migration(migrations.Migration):
    dependencies = [("stays", "0008_stayaddonpackage_staylistingaddon_staycapacityreview_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
