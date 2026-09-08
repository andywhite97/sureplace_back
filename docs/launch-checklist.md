# SurePlace Launch Checklist

Last updated: 2026-09-08

## Required Before Production

- Frontend unit tests pass with `cmd /c npm test -- --watch=false` from `sureplace`.
- Frontend production build passes with `cmd /c npm run build` from `sureplace`.
- Frontend dependency audit passes with `cmd /c npm audit --audit-level=high` from `sureplace`.
- Frontend CI workflow passes for pull requests and protected branches.
- Backend tests pass in an environment with Django and backend dependencies installed.
- API smoke tests pass against staging for authentication, property search/detail, stay search/detail, saved searches, messaging, viewing requests, bookings, manager listing creation, media upload, verification request creation, and moderation/admin flows.
- Staging environment variables are confirmed for database, CORS/CSRF, Bird email, media storage, payment, maps, and public API URL values.
- Static assets and uploaded media are served over HTTPS.
- Error logging and request IDs are visible for frontend API failures and backend exceptions.
- Seed or production reference data is present for regions, currencies, listing types, stay types, and amenities.

## Frontend Release Checks

- Run `cmd /c npm test -- --watch=false`.
- Run `cmd /c npm run build`.
- Run `cmd /c npm audit --audit-level=high`.
- Smoke-test desktop and mobile viewport sizes for:
  - Home search mode switching.
  - Property search list/map/filter/saved-search flows.
  - Stay search list/map/filter/availability flows.
  - Property and stay detail contact/booking/viewing entry points.
  - Account dashboard, saved searches, notifications, messages, viewings, bookings, and favorites.
  - Manager dashboard, listing forms, image upload/reorder/cover/delete, rooms, calendar, manager viewings/bookings, and verification.

## Backend Release Checks

- Run `python manage.py test` after activating the backend virtual environment.
- Run migrations against staging and confirm there are no unapplied migrations.
- Confirm media upload limits and accepted MIME types for property, stay, room, and verification documents.
- Confirm ownership checks for manager-only property/stay/room/image endpoints.
- Confirm verification documents are private and not exposed through public media URLs.
- Confirm `EMAIL_PROVIDER=bird`, `BIRD_API_KEY`, `DEFAULT_FROM_EMAIL`, and `DEFAULT_FROM_NAME` are set on both web and Celery worker services.
- Confirm Bird sender-domain DNS is verified and a staging transactional email records a Bird `em_...` message ID as `accepted`.

## Launch Decision

Current local readiness status is conditional. The Angular frontend test and production build checks pass locally, but backend tests and live/staging end-to-end verification still need to run in the proper backend environment before a production launch decision.
