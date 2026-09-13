from properties.models import Amenity, ListingType, PropertyType
from stays.models import StayAmenity, StayType, BedConfiguration, BathroomType
from verification.models import VerificationType

COUNTRIES = {
    "SZ": {
        "label": "Eswatini",
        "regions": [
            {"value": "HHOHHO", "label": "Hhohho", "areas": ["Mbabane", "Ezulwini", "Lobamba"]},
            {"value": "MANZINI", "label": "Manzini", "areas": ["Manzini", "Matsapha"]},
            {"value": "LUBOMBO", "label": "Lubombo", "areas": ["Siteki"]},
            {"value": "SHISELWENI", "label": "Shiselweni", "areas": []},
        ],
    }
}


def choices(values):
    return [{"value": value, "label": label} for value, label in values]


def reference_data():
    return {
        "property_types": choices(PropertyType.choices),
        "property_amenities": list(Amenity.objects.filter(is_active=True).values("id", "name", "slug", "category")),
        "listing_types": choices(ListingType.choices),
        "stay_types": choices(StayType.choices),
        "bed_configurations": choices(BedConfiguration.choices),
        "bathroom_types": choices(BathroomType.choices),
        "stay_amenities": list(StayAmenity.objects.filter(is_active=True).values("id", "name", "slug", "category")),
        "regions": COUNTRIES["SZ"]["regions"],
        "countries": [{"value": key, "label": value["label"]} for key, value in COUNTRIES.items()],
        "currencies": [{"value": "SZL", "label": "Swazi lilangeni"}],
        "verification_types": choices(VerificationType.choices),
    }
