from django.conf import settings


def frontend_config():
    return {
        "default_country": settings.DEFAULT_COUNTRY,
        "default_currency": settings.DEFAULT_CURRENCY,
        "supported_currencies": [settings.DEFAULT_CURRENCY],
        "features": settings.FEATURE_FLAGS,
        "map": {
            "default_latitude": settings.MAP_DEFAULT_LATITUDE,
            "default_longitude": settings.MAP_DEFAULT_LONGITUDE,
            "default_zoom": settings.MAP_DEFAULT_ZOOM,
        },
    }
