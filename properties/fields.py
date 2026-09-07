from django.conf import settings
from django.db import models


def location_field(*args, **kwargs):
    """Use a GIS point normally and JSON coordinates in explicit SQLite mode."""
    kwargs.setdefault("null", True)
    kwargs.setdefault("blank", True)
    if settings.USE_SQLITE:
        return models.JSONField(*args, **kwargs)
    from django.contrib.gis.db import models as gis_models

    kwargs.setdefault("geography", True)
    kwargs.setdefault("srid", 4326)
    return gis_models.PointField(*args, **kwargs)
