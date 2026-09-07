from django.db import connection
from django.http import JsonResponse
from django.conf import settings
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
    return JsonResponse(reference_data())


def config(request):
    return JsonResponse(frontend_config())
