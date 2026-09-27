from django.conf import settings


FOOTER_CONFIG = {
    "navigation_groups": [
        {
            "key": "explore",
            "title": "Explore",
            "order": 1,
            "items": [
                {"label": "Properties", "route": "/properties", "external_url": None, "order": 1, "is_active": True, "opens_in_new_tab": False},
                {"label": "Stays", "route": "/stays", "external_url": None, "order": 2, "is_active": True, "opens_in_new_tab": False},
                {"label": "Agents", "route": "/agents", "external_url": None, "order": 3, "is_active": True, "opens_in_new_tab": False},
                {"label": "Verification", "route": "/verification", "external_url": None, "order": 4, "is_active": True, "opens_in_new_tab": False},
            ],
        },
        {
            "key": "owners",
            "title": "For Owners",
            "order": 2,
            "items": [
                {"label": "List a property", "route": "/account/manage/properties/new", "external_url": None, "order": 1, "is_active": True, "opens_in_new_tab": False},
                {"label": "List a stay", "route": "/account/manage/stays/new", "external_url": None, "order": 2, "is_active": True, "opens_in_new_tab": False},
            ],
        },
        {"key": "support", "title": "Support", "order": 3, "items": [
            {"label": "Help Centre", "route": "/help", "external_url": None, "order": 1, "is_active": True, "opens_in_new_tab": False},
        ]},
        {"key": "company", "title": "Company", "order": 4, "items": [
            {"label": "About SurePlace", "route": "/about", "external_url": None, "order": 1, "is_active": True, "opens_in_new_tab": False},
            {"label": "Pricing", "route": "/pricing", "external_url": None, "order": 2, "is_active": True, "opens_in_new_tab": False},
        ]},
        {"key": "legal", "title": "Legal", "order": 5, "items": [
            {"label": "Terms", "route": "/terms", "external_url": None, "order": 1, "is_active": True, "opens_in_new_tab": False},
            {"label": "Privacy", "route": "/privacy", "external_url": None, "order": 2, "is_active": True, "opens_in_new_tab": False},
            {"label": "Cookies", "route": "/cookies", "external_url": None, "order": 3, "is_active": True, "opens_in_new_tab": False},
        ]},
    ],
    "social_links": [],
    "newsletter": {"enabled": False},
}


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
        "footer": FOOTER_CONFIG,
    }
