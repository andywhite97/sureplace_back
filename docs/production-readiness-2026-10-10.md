# Production readiness review — 10 October 2026

Launch decision: **not yet cleared for production**. Local application checks are
passing, but production credentials and infrastructure verification remain open.
This review is source analysis and automated local validation; it is not a claim
that every screen was exercised against a deployed production environment.

## Changes made

- Fixed the undefined `ValidationError` in the property pause operation and added
  a regression test proving a draft returns HTTP 400 without changing its status.
- Removed three unused imports/variables identified by Ruff.
- Added optional `SUREPLACE_ENV_FILE` selection while preserving the existing
  development `.env` default and platform environment-variable precedence.
- Created an ignored `.env.production` with a new random secret, production URLs,
  debug disabled, secure cookies, HTTPS redirect and HSTS. Provider secrets remain
  blank; no development database credentials were copied into production.
- Excluded production dotenv files and local QA artifacts from Docker contexts.
- Added shared Django Redis caching through `CACHE_URL`. Production startup now
  requires this setting and a secret of at least 50 characters. The former
  process-local cache did not share API throttle counters across Gunicorn workers.
- Removed migrations from the Docker image build. Configure migrations as the web
  service pre-deploy command against the runtime database.
- Corrected deployment instructions that referred to a nonexistent `render.yaml`.
- Updated vulnerable Python HTTP/JWT dependencies and frontend Angular packages.
- Replaced the vulnerable manual Pages publisher with `gh-pages` 6.1.1 and added
  a compatible patched UUID override for Xcode tooling. Checked UUID generation
  and publisher CLI arguments without publishing anything.
- Released temporary logo-upload object URLs after completion or cancellation.
- Bounded prerender discovery requests to three seconds per attempt so an offline
  API does not exhaust Angular's route-extraction timeout. API failures fall back
  to client rendering; deployment must still verify that important listing URLs
  appear in the sitemap and contain prerendered metadata.

## Validation results

- Backend full suite: 228 tests, passed, two PostgreSQL-specific tests skipped.
  Uses an isolated test database, in-memory Celery transport/result backend and
  test-only fast hashing; no live email/upload integrations are exercised.
- Property/core regression suite after the new draft-pause test: 51 tests passed,
  one PostgreSQL-specific test skipped.
- Python dependency vulnerability scan: zero known advisories after patching.
- Frontend dependency installation audit: zero known advisories after patching.
- Ruff, Python compilation and Git whitespace checks passed.
- Frontend suite on Node 24.19.0: all 428 tests passed across 83 files. The new
  timeout regression was then verified in the seven-test route-discovery suite.
- Production GitHub Pages build passed: 13 static routes and 11 indexable sitemap
  URLs. Dynamic listing/profile routes were absent from this build; verify public
  data and discovery against staging before launch. This output alone does not
  establish that the production API was unreachable.
- Bundle warnings remain: initial bundle 617.75 kB versus the 500 kB warning
  budget, plus component style warnings. Error budgets were not relaxed.

## Review coverage

| Area | Evidence and remaining limits |
| --- | --- |
| Accounts and access control | Authentication, email verification, password, agency permissions and owner/staff access tests in the backend suite. JWT access expires in 15 minutes; refresh rotation and blacklisting configured. |
| Listings and stays | Search/detail, publication transitions, availability, rooms, media ownership and public visibility covered by automated tests. |
| Bookings and viewings | Validation, guest/host scope, inventory and transactional notification tests pass locally. PostgreSQL locking tests are skipped on SQLite and remain a launch gate. |
| Messaging and notifications | Conversation authorization, read state, preferences and notification/email tests; frontend polling changes included in the frontend suite. Worker and scheduler operation require staging validation. |
| Uploads and verification | Public Cloudinary media and explicit private verification storage reviewed; authorization tests included. Actual production uploads and authenticated document delivery are unverified. |
| SEO | Earlier SEO audit checked canonical URLs, private-page noindex, cover-image social metadata, structured data and sitemap/prerender output. See frontend `docs/seo-audit-2026-10-09.md`. Live crawler/indexing results remain external checks. |
| Deployment and security | Production settings, dependency advisories, secret exclusions, CORS/CSRF, HTTPS, shared throttles, Docker build and deployment documentation reviewed. |
| Operations | Database health and Redis readiness endpoints exist. Database backups/restore, alert routing, sender-domain verification and worker/Beat monitoring require deployment evidence. |
| Performance and usability | Existing responsive changes and frontend tests reviewed. Production bundle warnings remain; a real-device/accessibility/load test is still required before broad launch. |

## Environment handoff

The production file is `sureplace_back/.env.production`. It is ignored by Git and
Docker and must stay private. Complete these eight values:

```text
DATABASE_URL
CACHE_URL
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
CLOUDINARY_CLOUD_NAME
CLOUDINARY_API_KEY
CLOUDINARY_API_SECRET
BIRD_API_KEY
```

Use PostgreSQL with PostGIS and a production Redis service. Use a separate cache
database/instance from Celery queues. External Redis connections should use TLS.
The Bird key must have a supported regional prefix. Verify the configured sender
address with Bird; a provider acceptance ID alone does not prove inbox delivery.
The configured API hostname is the existing Render hostname; add an explicit
custom API hostname if one is provisioned.

Run the dependency-free checker before loading the file:

```powershell
python scripts/check-production-env.py .env.production
$env:SUREPLACE_ENV_FILE = (Resolve-Path .env.production).Path
python manage.py check --deploy
python manage.py migrate --check
```

These Django commands must run in the actual deployment environment with the
required native PostGIS libraries and real credentials. On Render, import values
into a shared Environment Group for web, worker and Beat instead of shipping the
file inside the Docker image. Never copy backend secrets into Angular bundles.

## Remaining launch gates

1. Complete and verify the environment values; the checker currently correctly
   reports eight missing settings. Production `check --deploy` cannot be certified
   against this incomplete file.
2. Run the two skipped PostgreSQL tests against a disposable PostGIS database,
   including concurrent last-room reservation. The local Docker engine was not
   available during this review.
3. Deploy to staging, apply migrations, seed real reference data and test signup,
   verification email, login/refresh/logout, enquiries/viewings, booking request
   and host action, conversation reads, and notification delivery end to end.
4. Confirm public image uploads and protected verification documents; confirm a
   Celery worker processes tasks and exactly one Beat schedules expiry/reminders.
5. Verify TLS, allowed origins, database/Redis readiness, error alerting, backups
   and a successful restore. Remove demo accounts/listings from a public launch
   database rather than running the demo seed command there.
6. Record production browser performance, accessibility and last-room/load checks.

## Standards consulted

- [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [Django Redis cache configuration](https://docs.djangoproject.com/en/5.2/topics/cache/#redis)

The cache improves shared counters but DRF throttles are not a substitute for
edge-level abuse protection or an exact concurrency limiter.
