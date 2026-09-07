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
                         +-> external email provider
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
   API hostname and custom API domain, `CORS_ALLOWED_ORIGINS` and
   `FRONTEND_BASE_URL` to the Angular HTTPS origin, all three Cloudinary values,
   and the production email provider values. Shared values may live in a Render
   Environment Group.
4. Deploy. Docker installs GDAL/GEOS, `build.sh` installs Python dependencies and
   collects WhiteNoise static assets, and `preDeployCommand` runs migrations.
5. In a Render shell, run `python manage.py createsuperuser`.
6. Verify `GET /api/health/` returns `{"status":"ok","database":"up"}`.
7. Upload an avatar and listing image and confirm their URLs use Cloudinary.
8. Submit a test notification task and inspect the Celery worker logs. Confirm Beat
   is the sole scheduler and test delivery through the configured email provider.

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

Render's health check uses only the database. Redis, Cloudinary, and email checks
belong in deployment smoke tests so routine health polling does not call external
providers or enqueue work.
