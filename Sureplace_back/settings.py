"""Django settings for the SurePlace API."""

from datetime import timedelta
from pathlib import Path

import environ
from core.storage import public_media_backend

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False), USE_SQLITE=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="unsafe-development-key-change-me")
DEBUG = env("DEBUG")
USE_SQLITE = env("USE_SQLITE")
USE_CLOUDINARY = env.bool("USE_CLOUDINARY", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH", default=None)
GEOS_LIBRARY_PATH = env("GEOS_LIBRARY_PATH", default=None)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "core",
    "accounts",
    "agencies",
    "properties",
    "stays",
    "verification",
    "messaging",
    "bookings",
    "favourites",
    "alerts",
    "notifications",
    "moderation",
]
if USE_CLOUDINARY:
    INSTALLED_APPS.insert(6, "cloudinary_storage")
    INSTALLED_APPS.insert(7, "cloudinary")
# GeoDjango is enabled for the normal PostGIS configuration. The explicit SQLite
# test mode avoids importing native GDAL/GEOS libraries on machines without them.
if not USE_SQLITE:
    INSTALLED_APPS.insert(6, "django.contrib.gis")
MIDDLEWARE = [
    "core.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "Sureplace_back.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "Sureplace_back.wsgi.application"
ASGI_APPLICATION = "Sureplace_back.asgi.application"

if USE_SQLITE:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {"default": env.db("DATABASE_URL", default="postgis://sureplace:sureplace@localhost:5432/sureplace")}
    DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Mbabane"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": public_media_backend(USE_CLOUDINARY)},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = {
        "CLOUD_NAME": env("CLOUDINARY_CLOUD_NAME"),
        "API_KEY": env("CLOUDINARY_API_KEY"),
        "API_SECRET": env("CLOUDINARY_API_SECRET"),
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
BOOKING_HOLD_MINUTES = env.int("BOOKING_HOLD_MINUTES", default=30)

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:4200"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "auth_register": env("THROTTLE_AUTH_REGISTER", default="10/hour"),
        "auth_login": env("THROTTLE_AUTH_LOGIN", default="20/hour"),
        "password_reset": env("THROTTLE_PASSWORD_RESET", default="5/hour"),
        "guest_enquiry": env("THROTTLE_GUEST_ENQUIRY", default="10/hour"),
        "internal_message": env("THROTTLE_INTERNAL_MESSAGE", default="120/hour"),
        "viewing_request": env("THROTTLE_VIEWING_REQUEST", default="20/hour"),
        "booking_create": env("THROTTLE_BOOKING_CREATE", default="20/hour"),
        "verification_upload": env("THROTTLE_VERIFICATION_UPLOAD", default="30/hour"),
        "listing_report": env("THROTTLE_LISTING_REPORT", default="20/hour"),
    },
}
SPECTACULAR_SETTINGS = {
    "TITLE": "SurePlace API",
    "DESCRIPTION": "SurePlace property and stays marketplace API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "DISABLE_ERRORS_AND_WARNINGS": True,
}
SILENCED_SYSTEM_CHECKS = ["drf_spectacular.W001", "drf_spectacular.W002"]
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_PROVIDER = env("EMAIL_PROVIDER", default="django").lower()
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="SurePlace <noreply@sureplace.co.sz>")
DEFAULT_FROM_NAME = env("DEFAULT_FROM_NAME", default="SurePlace")
DEFAULT_REPLY_TO_EMAIL = env("DEFAULT_REPLY_TO_EMAIL", default="")
EMAIL_LOGO_URL = env("EMAIL_LOGO_URL", default="")
BIRD_API_KEY = env("BIRD_API_KEY", default="")
BIRD_API_BASE_URL = env("BIRD_API_BASE_URL", default="")
BIRD_REQUEST_TIMEOUT_SECONDS = env.int("BIRD_REQUEST_TIMEOUT_SECONDS", default=10)
BIRD_TRACK_OPENS = env.bool("BIRD_TRACK_OPENS", default=False)
BIRD_TRACK_CLICKS = env.bool("BIRD_TRACK_CLICKS", default=False)
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:4200")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
MESSAGE_EMAIL_COOLDOWN_MINUTES = env.int("MESSAGE_EMAIL_COOLDOWN_MINUTES", default=30)
PROPERTY_AVAILABILITY_REMINDER_DAYS = env.int("PROPERTY_AVAILABILITY_REMINDER_DAYS", default=7)
PROPERTY_AVAILABILITY_STALE_DAYS = env.int("PROPERTY_AVAILABILITY_STALE_DAYS", default=30)
CELERY_BEAT_SCHEDULE = {
    "saved-searches": {
        "task": "notifications.tasks.evaluate_saved_searches",
        "schedule": env.int("SAVED_SEARCH_INTERVAL_SECONDS", default=900),
    },
    "expire-bookings": {"task": "notifications.tasks.expire_bookings_task", "schedule": 300},
    "availability-reminders": {"task": "notifications.tasks.property_availability_reminders", "schedule": 86400},
}
VERIFICATION_MAX_FILE_MB = env.int("VERIFICATION_MAX_FILE_MB", default=10)
VERIFICATION_DOCUMENT_ROOT = BASE_DIR / "private_media"
DEFAULT_COUNTRY = env("DEFAULT_COUNTRY", default="SZ")
DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", default="SZL")
MAP_DEFAULT_LATITUDE = env.float("MAP_DEFAULT_LATITUDE", default=-26.5225)
MAP_DEFAULT_LONGITUDE = env.float("MAP_DEFAULT_LONGITUDE", default=31.4659)
MAP_DEFAULT_ZOOM = env.int("MAP_DEFAULT_ZOOM", default=8)
FEATURE_FLAGS = {
    "properties": env.bool("PROPERTIES_ENABLED", default=True),
    "stays": env.bool("STAYS_ENABLED", default=True),
    "bookings": env.bool("BOOKINGS_ENABLED", default=True),
    "internal_messaging": env.bool("INTERNAL_MESSAGING_ENABLED", default=True),
    "registration": env.bool("REGISTRATION_ENABLED", default=True),
}
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        environment=env("SENTRY_ENVIRONMENT", default="production"),
    )
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"structured": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "structured"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

if not DEBUG:
    if SECRET_KEY == "unsafe-development-key-change-me":
        raise RuntimeError("Set SECRET_KEY when DEBUG is false.")
    if USE_SQLITE:
        raise RuntimeError("SQLite is not allowed when DEBUG is false.")
    if not USE_CLOUDINARY:
        raise RuntimeError("Cloudinary media storage is required when DEBUG is false.")
    if EMAIL_PROVIDER != "bird":
        raise RuntimeError("Set EMAIL_PROVIDER=bird when DEBUG is false.")
    if not BIRD_API_KEY:
        raise RuntimeError("Set BIRD_API_KEY when EMAIL_PROVIDER=bird.")
    if BIRD_API_KEY.split("_", 2)[0:2] not in [["bk", "us1"], ["bk", "eu1"]]:
        raise RuntimeError("BIRD_API_KEY must include a supported region such as bk_us1_ or bk_eu1_.")
    if BIRD_API_BASE_URL:
        from urllib.parse import urlparse

        bird_base = urlparse(BIRD_API_BASE_URL)
        if (
            bird_base.scheme != "https"
            or bird_base.netloc not in {"us1.platform.bird.com", "eu1.platform.bird.com"}
            or bird_base.path not in {"", "/"}
        ):
            raise RuntimeError("BIRD_API_BASE_URL must be a supported Bird HTTPS regional host.")
    if any(host in {"localhost", "127.0.0.1"} for host in ALLOWED_HOSTS):
        raise RuntimeError("Production ALLOWED_HOSTS must not contain localhost.")
