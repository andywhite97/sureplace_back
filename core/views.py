from django.db import connection
from django.http import JsonResponse
from django.conf import settings
from django.core.cache import cache
from .features import frontend_config
from .reference import reference_data


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unavailable", "database": "down"}, status=503)
    return JsonResponse({"status": "ok", "database": "up"})


def ready(request):
    response = health(request)
    if response.status_code != 200:
        return response
    try:
        from redis import Redis

        Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1).ping()
    except Exception:
        return JsonResponse({"status": "unavailable", "database": "up", "redis": "down"}, status=503)
    return JsonResponse({"status": "ok", "database": "up", "redis": "up"})


def reference(request):
    data = cache.get_or_set("public-reference:v1", reference_data, settings.PUBLIC_REFERENCE_CACHE_SECONDS)
    response = JsonResponse(data)
    response["Cache-Control"] = f"public, max-age={settings.PUBLIC_REFERENCE_CACHE_SECONDS}"
    return response


def config(request):
    data = cache.get_or_set("public-config:v1", frontend_config, settings.PUBLIC_CONFIG_CACHE_SECONDS)
    response = JsonResponse(data)
    response["Cache-Control"] = f"public, max-age={settings.PUBLIC_CONFIG_CACHE_SECONDS}"
    return response
