"""
WSGI config for Sureplace_back project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os
import time

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Sureplace_back.settings")

started = time.monotonic()
application = get_wsgi_application()
print(f"sureplace_startup stage=wsgi_ready duration_ms={(time.monotonic() - started) * 1000:.2f}", flush=True)
