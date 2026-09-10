LOCATIONS = [
    {"town": "Mbabane", "region": "Hhohho", "latitude": -26.3054, "longitude": 31.1367},
    {"town": "Manzini", "region": "Manzini", "latitude": -26.4988, "longitude": 31.3800},
    {"town": "Ezulwini", "region": "Hhohho", "latitude": -26.4017, "longitude": 31.1775},
    {"town": "Matsapha", "region": "Manzini", "latitude": -26.5167, "longitude": 31.3167},
    {"town": "Lobamba", "region": "Hhohho", "latitude": -26.4667, "longitude": 31.2000},
    {"town": "Siteki", "region": "Lubombo", "latitude": -26.4500, "longitude": 31.9500},
    {"town": "Malkerns", "region": "Manzini", "latitude": -26.5667, "longitude": 31.1833},
    {"town": "Nhlangano", "region": "Shiselweni", "latitude": -27.1122, "longitude": 31.1983},
    {"town": "Piggs Peak", "region": "Hhohho", "latitude": -25.9606, "longitude": 31.2474},
    {"town": "Big Bend", "region": "Lubombo", "latitude": -26.8167, "longitude": 31.9333},
]

CORE_TOWNS = {"Mbabane", "Manzini", "Ezulwini", "Matsapha", "Lobamba", "Siteki"}


def offset_location(location, index, seed):
    lat_offset = (((seed + index * 17) % 13) - 6) * 0.004
    lon_offset = (((seed + index * 23) % 15) - 7) * 0.004
    return location["latitude"] + lat_offset, location["longitude"] + lon_offset
