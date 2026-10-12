from decimal import Decimal
from django.db import migrations


def seed(apps, schema_editor):
    Plan = apps.get_model("properties", "PropertyPlan")
    Package = apps.get_model("properties", "PropertyAddOnPackage")
    for order, (code, name, price, limit, kinds) in enumerate([
        ("INDIVIDUAL_FREE", "Individual Free", "0", 2, ["INDIVIDUAL"]),
        ("AGENCY_FREE", "Agency Free", "0", 5, ["AGENCY"]),
        ("STARTER", "Starter", "149", 10, ["INDIVIDUAL", "AGENCY"]),
        ("PROFESSIONAL", "Professional", "349", 25, ["INDIVIDUAL", "AGENCY"]),
        ("AGENCY_PLUS", "Agency Plus", "699", 75, ["AGENCY"]),
    ]):
        Plan.objects.using(schema_editor.connection.alias).get_or_create(code=code, defaults={
            "display_name": name, "price": Decimal(price), "billing_interval": "FOREVER" if price == "0" else "MONTH",
            "active_listing_limit": limit, "display_order": order, "applicable_account_types": kinds,
        })
    for order, (code, name, price, quantity) in enumerate([
        ("SINGLE_EXTRA", "Single Listing", "49", 1), ("TRIPLE_EXTRA", "3-Listing Bundle", "129", 3),
    ]):
        Package.objects.using(schema_editor.connection.alias).get_or_create(code=code, defaults={
            "display_name": name, "price": Decimal(price), "quantity": quantity, "duration_days": 90, "display_order": order,
        })
    # Existing property rows are deliberately untouched, including over-limit inventory.


class Migration(migrations.Migration):
    dependencies = [("properties", "0007_propertyaddonpackage_propertyplan_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
