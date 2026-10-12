"""Isolated pricing/booking regressions. Never points at a production database."""

from properties.test_settings import *  # noqa: F403
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.db import connections
from django.db.models.signals import post_migrate


def seed_test_catalogues(sender, using, **kwargs):
    if sender.label == "stays":
        schema = SimpleNamespace(connection=connections[using])
        for module in (
            "properties.migrations.0008_property_pricing_catalogue",
            "stays.migrations.0009_stay_pricing_catalogue",
        ):
            import_module(module).seed(apps, schema)


post_migrate.connect(seed_test_catalogues, dispatch_uid="pricing_test_catalogues", weak=False)
