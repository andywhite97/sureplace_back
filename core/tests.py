from unittest.mock import patch
import uuid
from django.core.files.storage import FileSystemStorage, storages
from django.test import SimpleTestCase, TestCase, override_settings
from django.core.management import call_command
from django.core.management.base import CommandError


class HealthTests(TestCase):
    def test_health_checks_database(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "up")

    @patch("redis.Redis.ping", return_value=True)
    def test_readiness_checks_redis(self, ping):
        self.assertEqual(self.client.get("/api/v1/health/ready/").status_code, 200)

    def test_request_id_is_accepted_and_returned(self):
        request_id = str(uuid.uuid4())
        response = self.client.get("/api/v1/config/", HTTP_X_REQUEST_ID=request_id)
        self.assertEqual(response["X-Request-ID"], request_id)

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get("/api/v1/config/", HTTP_X_REQUEST_ID="unsafe" * 100)
        uuid.UUID(response["X-Request-ID"])

    def test_reference_and_config_contracts(self):
        reference = self.client.get("/api/v1/reference/")
        config = self.client.get("/api/v1/config/")
        self.assertEqual(reference.status_code, 200)
        self.assertEqual(len(reference.json()["regions"]), 4)
        self.assertIn("property_amenities", reference.json())
        self.assertNotIn("api_secret", str(config.json()).lower())

    def test_v1_and_legacy_health_routes(self):
        self.assertEqual(self.client.get("/api/v1/health/").status_code, 200)
        self.assertEqual(self.client.get("/api/health/").status_code, 200)

    def test_openapi_and_docs_load(self):
        self.assertEqual(self.client.get("/api/v1/schema/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/docs/").status_code, 200)

    def test_standard_error_contract(self):
        response = self.client.get("/api/v1/notifications/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "not_authenticated")
        self.assertIn("request_id", response.json())


class StorageConfigurationTests(SimpleTestCase):
    @override_settings(
        USE_CLOUDINARY=False, STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    )
    def test_development_storage_is_local(self):
        storages._storages.clear()
        self.assertIsInstance(storages["default"], FileSystemStorage)

    def test_production_storage_selects_cloudinary(self):
        from core.storage import public_media_backend

        self.assertEqual(public_media_backend(True), "cloudinary_storage.storage.MediaCloudinaryStorage")

    def test_verification_storage_has_no_public_url(self):
        from verification.storage import private_verification_storage

        with self.assertRaises(ValueError):
            private_verification_storage.url("verification/id.pdf")

    @override_settings(DEBUG=False)
    def test_demo_reset_requires_yes_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_data", reset=True)
