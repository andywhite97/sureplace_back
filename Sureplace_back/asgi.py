"""
ASGI config for Sureplace_back project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os
import time

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Sureplace_back.settings")

started = time.monotonic()
application = get_asgi_application()
print(f"sureplace_startup stage=asgi_ready duration_ms={(time.monotonic() - started) * 1000:.2f}", flush=True)
