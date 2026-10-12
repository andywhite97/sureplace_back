"""Run property entitlement tests on an isolated, local PostgreSQL test database.

Uses the existing .env DATABASE_URL without printing credentials. JSON location
test mode keeps this focused on transactions, constraints and actual row locks.
"""

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
os.environ["PROPERTY_TEST_DATABASE_NAME"] = f"test_property_pricing_{uuid.uuid4().hex[:8]}"
os.environ["DJANGO_SETTINGS_MODULE"] = "properties.test_settings"
from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line(["manage.py", "test", "properties.tests_entitlements", "--noinput", "--verbosity=1"])
