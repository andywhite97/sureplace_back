# SurePlace production deployment

## Architecture

```text
Angular frontend -> Render Django web -> Render PostgreSQL + PostGIS
                         |        |
                         |        +-> Cloudinary public images
                         +-> Render Key Value -> Celery worker
                                               ^
                                               |
                                          Celery Beat
                         +-> Bird Email API
```

Celery Beat is the only periodic scheduler. It dispatches saved-search evaluation,
booking expiry, and availability reminders to the worker, so equivalent Render
Cron Jobs must not also be configured. Web and Celery processes use the same image
and environment. Runtime filesystem writes are never durable application media.

## Blueprint deployment

1. Connect the repository to a new Render Blueprint and select the repository-root
   `render.yaml`.
2. Choose appropriate paid plans and region for the database, Key Value, web,
   worker, and Beat services. The Blueprint intentionally does not prescribe cost.
3. Fill all `sync: false` variables. At minimum set `ALLOWED_HOSTS` to the Render
   API hostname and custom API domain, `CORS_ALLOWED_ORIGINS`,
   `CSRF_TRUSTED_ORIGINS`, and `FRONTEND_BASE_URL` to the Angular HTTPS origin,
   all three Cloudinary values, and the production Bird email provider values.
   Shared values may live in a Render Environment Group.
4. Deploy. Docker installs GDAL/GEOS, `build.sh` installs Python dependencies and
   collects WhiteNoise static assets, and `preDeployCommand` runs migrations.
5. In a Render shell, run `python manage.py createsuperuser`.
6. Verify `GET /api/health/` returns `{"status":"ok","database":"up"}`.
7. Upload an avatar and listing image and confirm their URLs use Cloudinary.
8. Submit a test notification task and inspect the Celery worker logs. Confirm Beat
   is the sole scheduler and test delivery through Bird. The logged Bird message
   ID means accepted by Bird, not final inbox delivery.

## Email environment

Set these variables on both the web service and Celery worker:

```text
EMAIL_PROVIDER=bird
EMAIL_DELIVERY_MODE=async
BIRD_API_KEY=<sync false secret>
BIRD_API_BASE_URL=<optional regional HTTPS override>
BIRD_REQUEST_TIMEOUT_SECONDS=10
DEFAULT_FROM_EMAIL=SurePlace <noreply@verified-domain>
DEFAULT_FROM_NAME=SurePlace
DEFAULT_REPLY_TO_EMAIL=<optional support mailbox>
EMAIL_LOGO_URL=<optional public logo URL>
BIRD_TRACK_OPENS=false
BIRD_TRACK_CLICKS=false
```

The Bird API key is region-aware. When no override is set, keys such as
`bk_us1_...` and `bk_eu1_...` select `https://us1.platform.bird.com` and
`https://eu1.platform.bird.com`. Do not put Bird credentials in Angular
environment variables. See `docs/email.md` for sender-domain verification and
delivery-status semantics.

## Frontend origins

GitHub Pages runs on a different origin from the Render API, so production CORS
must list the frontend origins exactly. Origins do not include paths.

Custom domain:

```text
CORS_ALLOWED_ORIGINS=https://sureplace.twinpeaksinvestment.com
CSRF_TRUSTED_ORIGINS=https://sureplace.twinpeaksinvestment.com
FRONTEND_BASE_URL=https://sureplace.twinpeaksinvestment.com
```

Repository Pages fallback:

```text
CORS_ALLOWED_ORIGINS=https://andywhite97.github.io
CSRF_TRUSTED_ORIGINS=https://andywhite97.github.io
FRONTEND_BASE_URL=https://andywhite97.github.io/sureplace
```

SurePlace uses JWT for API authentication, but CSRF trusted origins should still
be configured for any Django endpoint or future browser behavior that relies on
CSRF checks. Keep frontend and backend URLs HTTPS in production.

The database URL injected by Render is deliberately forced through Django's
PostGIS engine. Migration `properties.0000_enable_postgis` runs `CREATE EXTENSION
IF NOT EXISTS postgis` via Django's extension operation before spatial fields are
created. Verify production with:

```sql
SELECT PostGIS_Version();
```

If the Render database role cannot create extensions, enable PostGIS once from the
Render database administration interface before the first migration.

## Media and static files

`USE_CLOUDINARY=true` selects Cloudinary as Django's default storage for public
avatars, agency logos, property images, stay images, and room images. Their upload
paths are grouped below `sureplace/` without email addresses or other sensitive
identifiers. Cloudinary can generate responsive `f_auto,q_auto` transformations
from the stored asset identifiers; the backend does not create resized copies.

Verification documents use their explicit storage instead of default public media.
In production they upload as Cloudinary `raw` assets with authenticated delivery,
and the API streams them only after its existing authorization check. Their storage
never provides a public URL. Locally they remain under ignored `private_media/`.
Do not change verification files to the default Cloudinary media storage.

WhiteNoise serves collected Django/admin assets from `staticfiles/`. Cloudinary is
not used for static assets. Neither `media/`, `private_media/`, nor `staticfiles/`
is a production persistence dependency.

## Commands and operational checks

```text
Web:       gunicorn Sureplace_back.wsgi:application --bind 0.0.0.0:$PORT
Worker:    celery -A Sureplace_back worker -l info
Scheduler: celery -A Sureplace_back beat -l info
Migration: python manage.py migrate --noinput
Static:    python manage.py collectstatic --no-input
```

Before deploying, run the SQLite unit suite with `USE_SQLITE=true` and run a staging
suite against genuine PostgreSQL/PostGIS with `USE_SQLITE=false` and a disposable
`DATABASE_URL`. Automated tests must keep `USE_CLOUDINARY=false`; they never upload
to a real Cloudinary account. Rotate any credential that is accidentally committed.

Render's health check uses only the database. Redis, Cloudinary, and Bird checks
belong in deployment smoke tests so routine health polling does not call external
providers or enqueue work.
