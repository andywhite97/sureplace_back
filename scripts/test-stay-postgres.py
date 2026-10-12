"""Validate real row locks and booking safety against an isolated LOCAL test DB."""

import os
import sys
import uuid
from pathlib import Path
import environ

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
env = environ.Env()
environ.Env.read_env(root / ".env")
database = env.db("DATABASE_URL")
if database.get("HOST") not in {"localhost", "127.0.0.1", "::1"}:
    raise SystemExit("Refusing to run this helper against a non-local database.")
os.environ["PROPERTY_TEST_DATABASE_URL"] = env("DATABASE_URL")
os.environ["PROPERTY_TEST_DATABASE_NAME"] = f"test_stay_pricing_{uuid.uuid4().hex[:8]}"
os.environ["DJANGO_SETTINGS_MODULE"] = "stays.test_settings"
from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line(
    [
        "manage.py",
        "test",
        "stays.tests_entitlements",
        "bookings.tests_concurrency",
        "properties.tests_entitlements",
        "--noinput",
        "--verbosity=1",
    ]
)
