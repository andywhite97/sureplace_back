FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

RUN apt-get update && apt-get install -y --no-install-recommends \
    binutils gdal-bin libgdal-dev libgeos-dev libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN USE_SQLITE=true DEBUG=true SECRET_KEY=build-only-secret-key-not-used-at-runtime bash build.sh

CMD ["sh","-c","gunicorn Sureplace_back.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-3} --access-logfile -"]
