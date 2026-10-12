"""Isolated property tests; optional PostgreSQL exercises actual row-lock concurrency.

Location fields stay in the project's existing JSON test mode. This does not
replace PostGIS/geography integration tests or change production settings.
"""

import os

os.environ["USE_SQLITE"] = "true"
os.environ["USE_CLOUDINARY"] = "false"
from Sureplace_back.settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_DELIVERY_MODE = "sync"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
if os.environ.get("PROPERTY_TEST_SQLITE_PATH"):
    DATABASES["default"]["NAME"] = os.environ["PROPERTY_TEST_SQLITE_PATH"]
if os.environ.get("PROPERTY_TEST_DATABASE_URL"):
    DATABASES = {"default": env.db("PROPERTY_TEST_DATABASE_URL")}  # noqa: F405
    DATABASES["default"]["ENGINE"] = "django.db.backends.postgresql"
    DATABASES["default"]["TEST"] = {"NAME": os.environ.get("PROPERTY_TEST_DATABASE_NAME", "test_property_pricing")}
