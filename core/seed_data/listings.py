from decimal import Decimal

from properties.models import ListingStatus, ListingType, PropertyType
from stays.models import StayStatus, StayType

PROPERTY_TITLES = [
    ("Modern 2-Bedroom Flat in Mbabane", PropertyType.FLAT, ListingType.RENT, 5500),
    ("Family Home in Ezulwini Valley", PropertyType.HOUSE, ListingType.SALE, 2450000),
    ("Furnished Apartment Near Manzini CBD", PropertyType.APARTMENT, ListingType.RENT, 6800),
    ("Matsapha Warehouse Unit", PropertyType.WAREHOUSE, ListingType.RENT, 18000),
    ("Lobamba Townhouse Near Main Road", PropertyType.TOWNHOUSE, ListingType.RENT, 7200),
    ("Siteki Hills Starter Home", PropertyType.HOUSE, ListingType.SALE, 750000),
    ("Malkerns Residential Plot", PropertyType.LAND, ListingType.SALE, 450000),
    ("Nhlangano Three-Bedroom Home", PropertyType.HOUSE, ListingType.RENT, 6200),
    ("Piggs Peak Mountain Cottage", PropertyType.HOUSE, ListingType.SALE, 1200000),
    ("Big Bend Shop Front", PropertyType.SHOP, ListingType.RENT, 9800),
    ("Mbabane Office Suite", PropertyType.OFFICE, ListingType.RENT, 12500),
    ("Manzini Two-Bedroom Apartment", PropertyType.APARTMENT, ListingType.RENT, 4800),
    ("Executive Home in Ezulwini", PropertyType.HOUSE, ListingType.RENT, 18000),
    ("Matsapha Commercial Yard", PropertyType.COMMERCIAL, ListingType.SALE, 4200000),
    ("Lobamba Residential Plot", PropertyType.LAND, ListingType.SALE, 520000),
    ("Siteki Retail Space", PropertyType.SHOP, ListingType.RENT, 7600),
    ("Mbabane Garden Townhouse", PropertyType.TOWNHOUSE, ListingType.RENT, 8500),
    ("Manzini Family House", PropertyType.HOUSE, ListingType.SALE, 1600000),
    ("Ezulwini Self-Contained Flat", PropertyType.FLAT, ListingType.RENT, 3900),
    ("Matsapha Staff Accommodation Block", PropertyType.OTHER, ListingType.RENT, 14500),
    ("Lobamba Compact Apartment", PropertyType.APARTMENT, ListingType.RENT, 3600),
    ("Siteki Smallholding", PropertyType.LAND, ListingType.SALE, 880000),
    ("Mbabane Premium Residence", PropertyType.HOUSE, ListingType.SALE, 4500000),
    ("Manzini Central Office", PropertyType.OFFICE, ListingType.RENT, 11000),
    ("Ezulwini Valley Townhouse", PropertyType.TOWNHOUSE, ListingType.SALE, 1850000),
    ("Matsapha Light Industrial Warehouse", PropertyType.WAREHOUSE, ListingType.SALE, 3900000),
    ("Malkerns Cottage Rental", PropertyType.HOUSE, ListingType.RENT, 5200),
    ("Nhlangano Main Street Shop", PropertyType.SHOP, ListingType.SALE, 980000),
    ("Piggs Peak Apartment", PropertyType.APARTMENT, ListingType.RENT, 4200),
    ("Big Bend Family Rental", PropertyType.HOUSE, ListingType.RENT, 5800),
]

STAY_NAMES = [
    ("Ezulwini Valley Guest House", StayType.GUEST_HOUSE, 850),
    ("Mbabane Central Suites", StayType.HOTEL, 1200),
    ("Malkerns Country Lodge", StayType.LODGE, 950),
    ("Manzini Garden B&B", StayType.BNB, 650),
    ("Lobamba Heritage Stay", StayType.GUEST_HOUSE, 780),
    ("Siteki Hills Lodge", StayType.LODGE, 900),
    ("Matsapha Business Hotel", StayType.HOTEL, 1100),
    ("Piggs Peak Mountain Retreat", StayType.LODGE, 1350),
    ("Big Bend Riverside Rooms", StayType.GUEST_HOUSE, 700),
    ("Nhlangano Family B&B", StayType.BNB, 620),
    ("Mbabane Short Stay Apartments", StayType.SHORT_STAY, 750),
    ("Ezulwini Self-Catering Villas", StayType.SELF_CATERING, 1600),
    ("Manzini Transit Hostel", StayType.HOSTEL, 450),
    ("Matsapha Serviced Studios", StayType.SELF_CATERING, 820),
    ("Lobamba Garden Cottages", StayType.SELF_CATERING, 980),
    ("Siteki Traveller Rooms", StayType.BNB, 580),
    ("Malkerns Valley Resort", StayType.RESORT, 2500),
    ("Mbabane Guest Lodge", StayType.GUEST_HOUSE, 900),
    ("Ezulwini Boutique Hotel", StayType.HOTEL, 1800),
    ("Big Bend Farm Stay", StayType.OTHER, 680),
]

PROPERTY_STATUSES = [
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.PUBLISHED,
    ListingStatus.DRAFT,
    ListingStatus.SUBMITTED,
    ListingStatus.UNDER_REVIEW,
    ListingStatus.PAUSED,
    ListingStatus.REJECTED,
    ListingStatus.SUSPENDED,
]

STAY_STATUSES = [
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.PUBLISHED,
    StayStatus.DRAFT,
    StayStatus.SUBMITTED,
    StayStatus.PAUSED,
    StayStatus.REJECTED,
]


def property_description(title, town, listing_type):
    action = "renters" if listing_type == ListingType.RENT else "buyers"
    return (
        f"{title} offers a practical base in {town} with convenient access to shops, schools, "
        f"and commuter routes. The layout is suited to {action} who want clear details, sensible "
        "amenities, and a realistic sense of the neighbourhood before arranging the next step."
    )


def stay_description(name, town):
    return (
        f"{name} is a fictional SurePlace demo stay in {town}, created for testing search, booking, "
        "messaging, and availability flows. It has varied room options, local-style amenities, and "
        "a calm guest-facing profile suitable for development and staging demos."
    )


def decimal_price(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def scale_counts(total_count):
    properties = max(1, round(total_count * 0.6))
    stays = max(1, total_count - properties)
    return properties, stays
