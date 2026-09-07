import uuid
from decimal import Decimal, InvalidOperation
from rest_framework import serializers
from properties.models import ListingType, PropertyType
from stays.models import StayType

COMMON = {
    "region": str,
    "town": str,
    "suburb": str,
    "min_price": "decimal",
    "max_price": "decimal",
    "amenities": "uuids",
}
PROPERTY = {
    **COMMON,
    "listing_type": set(ListingType.values),
    "property_type": set(PropertyType.values),
    "min_bedrooms": "int",
    "min_bathrooms": "int",
    "furnished": bool,
    "pet_friendly": bool,
    "north": "decimal",
    "south": "decimal",
    "east": "decimal",
    "west": "decimal",
}
STAY = {**COMMON, "stay_type": set(StayType.values), "adults": "int", "children": "int", "rooms": "int"}


def validate_criteria(search_type, data):
    if not isinstance(data, dict):
        raise serializers.ValidationError("Criteria must be an object.")
    schema = PROPERTY if search_type == "PROPERTY" else STAY
    unknown = set(data) - set(schema)
    if unknown:
        raise serializers.ValidationError(f"Unknown criteria: {', '.join(sorted(unknown))}.")
    result = {}
    for key, value in data.items():
        rule = schema[key]
        try:
            if rule == "decimal":
                value = str(Decimal(str(value)))
            elif rule == "int":
                value = int(value)
                assert value >= 0
            elif rule == "uuids":
                value = [str(uuid.UUID(str(v))) for v in value]
            elif isinstance(rule, set) and value not in rule:
                raise ValueError
            elif rule is bool and not isinstance(value, bool):
                raise ValueError
            elif rule is str and not isinstance(value, str):
                raise ValueError
        except (ValueError, TypeError, InvalidOperation, AssertionError):
            raise serializers.ValidationError({key: "Invalid value."})
        result[key] = value
    if "min_price" in result and "max_price" in result and Decimal(result["min_price"]) > Decimal(result["max_price"]):
        raise serializers.ValidationError("min_price cannot exceed max_price.")
    return result
