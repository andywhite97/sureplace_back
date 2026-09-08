# SurePlace backend

SurePlace is an Eswatini-first marketplace with two deliberately separate domains:
long-term rentals/property sales (`properties`) and hospitality/short stays (`stays`).
This repository currently provides only the Django REST API foundation.

## Structure

- `Sureplace_back/`: project settings and root URL configuration
- `core/`: reusable timestamps, verification choices, and pagination
- `accounts/`: custom email-based user model and JWT authentication API
- `agencies/`: agencies and their multi-user agent profiles
- `properties/` and `stays/`: separate placeholders for future domain models
- `verification/`, `messaging/`, `bookings/`, `favourites/`, `alerts/`,
  `notifications/`, and `moderation/`: bounded contexts reserved for later phases

Onboarding intents are stored as a validated JSON list. They record what a user
wants to do initially, but are not roles or authorization rules. A single user may
therefore search, own properties, operate stays, and join agencies over time.

## Requirements

- Python 3.11+
- PostgreSQL with the PostGIS extension
- GDAL/GEOS native libraries required by GeoDjango

Python dependencies are listed in `requirements.txt`. PostgreSQL uses the PostGIS
backend by default; future listing models can use geographic `PointField` values and
spatial indexes without a database migration from plain coordinates.

## Local setup

From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Create the database and enable PostGIS (using a PostgreSQL administrator):

```sql
CREATE DATABASE sureplace;
\c sureplace
CREATE EXTENSION postgis;
```

Update `DATABASE_URL` and other settings in `.env`, then run:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Do not commit `.env`; only safe example values belong in `.env.example`.

## Tests

Tests cover registration, case-insensitive duplicate-email prevention, login,
authenticated profile access, JWT refresh, agency integrity, and agent membership.
Use PostGIS for integration parity:

```powershell
python manage.py test
```

For this foundation's model/API tests on a machine without PostgreSQL/PostGIS, use
the explicit SQLite switch (no spatial model exists yet):

```powershell
$env:USE_SQLITE = "true"
$env:DEBUG = "true"
python manage.py test
```

## Authentication API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register/` | Create an account |
| `POST` | `/api/auth/login/` | Obtain access and refresh JWTs |
| `POST` | `/api/auth/token/refresh/` | Exchange a refresh token |
| `GET` / `PATCH` | `/api/auth/me/` | Read or update the authenticated profile |

Send access tokens as `Authorization: Bearer <token>`. Registration accepts
`first_name`, `last_name`, `email`, `phone_number`, `password`, and optional
`onboarding_intents`. Phone numbers use E.164-style international format, such as
`+26876123456`.

## Properties domain

`PropertyListing` represents only long-term rentals and property sales. It uses a
UUID internally and an immutable public reference such as `SP-2026-A1B2C3D4E5`.
Locations are geographic SRID-4326 points under PostGIS. API responses expose
latitude and longitude, rather than GeoJSON internals. Listings support an owner,
an optional agency and agent, ordered images, a single cover image, and reusable
amenities. The initial amenity catalogue is installed by a data migration.

SQLite mode uses JSON coordinates behind the same model/serializer contract. It is
only intended for tests and local work without GDAL; deployed map queries use the
PostGIS geographic `PointField` and spatial operations.

### Lifecycle

Normal users create `DRAFT` listings and may move them to `SUBMITTED`, pause a
published listing, or confirm availability. Moderators/admins control review,
publication, rejection, suspension, verification, and featured placement.

`confirm-availability` sets `availability_status` to `AVAILABLE` and records an
UTC timestamp in `availability_confirmed_at`. The frontend can use that timestamp
to render wording such as “confirmed 2 days ago.”

### Property endpoints

| Method | Endpoint | Access |
| --- | --- | --- |
| `GET` | `/api/properties/` | Public published listings |
| `GET` | `/api/properties/{slug-or-uuid}/` | Public when published; managers for drafts |
| `GET` | `/api/properties/featured/` | Public, published/available/featured only |
| `POST` | `/api/properties/` | Authenticated; creates a draft |
| `PATCH` | `/api/properties/{slug-or-uuid}/` | Owner, assigned agent, or active agency staff |
| `DELETE` | `/api/properties/{slug-or-uuid}/` | Owner, assigned agent, or active agency staff |
| `POST` | `/api/properties/{slug-or-uuid}/submit/` | Authorized manager |
| `POST` | `/api/properties/{slug-or-uuid}/pause/` | Authorized manager |
| `POST` | `/api/properties/{slug-or-uuid}/confirm-availability/` | Authorized manager |

Filters are `listing_type`, `property_type`, `region`, `town`, `suburb`,
`min_price`, `max_price`, `min_bedrooms`, `min_bathrooms`, `furnished`,
`pet_friendly`, `amenities`, `featured`, and `verification_status`. Full-text-style
search across title, description and place names uses `search`. Ordering accepts
`newest`, `oldest`, `price_asc`, or `price_desc`.

Map bounds use all four query parameters together:

```text
/api/properties/?north=-26.0&south=-27.0&east=32.0&west=31.0
```

### Create example

```json
{
  "title": "Modern 3-bedroom house in Ezulwini",
  "description": "Spacious family home close to shops and schools.",
  "listing_type": "RENT",
  "property_type": "HOUSE",
  "price": "12500.00",
  "currency": "SZL",
  "region": "Hhohho",
  "town": "Ezulwini",
  "suburb": "Lobamba",
  "latitude": -26.399,
  "longitude": 31.176,
  "bedrooms": 3,
  "bathrooms": 2,
  "parking_spaces": 2,
  "amenities": ["<amenity-uuid>"]
}
```

List responses are paginated and contain compact cards with coordinates, cover
image, price, core property details, availability, and agent/agency summaries:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [{
    "id": "<uuid>",
    "public_id": "SP-2026-A1B2C3D4E5",
    "slug": "modern-3-bedroom-house-in-ezulwini",
    "title": "Modern 3-bedroom house in Ezulwini",
    "listing_type": "RENT",
    "property_type": "HOUSE",
    "price": "12500.00",
    "currency": "SZL",
    "latitude": -26.399,
    "longitude": 31.176,
    "cover_image": null
  }]
}
```

Detail responses add the full description, address, ordered `images`, `amenities`,
and expanded agency/agent summaries. An authenticated listing manager additionally
receives an internal `quality` object with a 0–100 score and improvement suggestions;
that object is omitted from ordinary public responses.

## Stays and room availability

Stays are a separate hospitality domain. A `Stay` owns reusable `StayAmenity`
records, an ordered single-cover gallery, and one or more `RoomType` records. Each
room type defines occupancy, inventory, base nightly price, minimum stay, and its
own gallery. `RoomAvailability` overrides inventory, price, blocking, or minimum
stay for one room and date; missing calendar rows use the room defaults.

Public and management endpoints:

```text
GET/POST          /api/stays/
GET               /api/stays/featured/
GET/PATCH/DELETE  /api/stays/{slug-or-uuid}/
POST              /api/stays/{slug-or-uuid}/submit/
POST              /api/stays/{slug-or-uuid}/pause/
GET/POST          /api/stays/{slug-or-uuid}/rooms/
GET               /api/stays/{slug-or-uuid}/availability/
GET/PATCH/DELETE  /api/rooms/{uuid}/
POST              /api/rooms/{uuid}/availability/bulk/
```

Stay filters include `stay_type`, location names, `featured`,
`verification_status`, `amenities`, `min_price`, `max_price`, and `search`.
Ordering accepts `newest`, `price_asc`, `price_desc`, or `name`.

Create a stay:

```json
{"name":"Mountain Lodge","stay_type":"LODGE","region":"Hhohho",
 "town":"Mbabane","latitude":-26.3,"longitude":31.1}
```

Create a room through the nested rooms endpoint:

```json
{"name":"Deluxe King Room","capacity_adults":2,"capacity_children":1,
 "total_capacity":3,"number_of_beds":1,"quantity":4,
 "base_price":"850.00","currency":"SZL","minimum_stay":1}
```

Update a calendar range:

```json
{"start_date":"2026-12-20","end_date":"2027-01-05",
 "available_units":2,"custom_price":"1200.00","is_blocked":false}
```

Search availability with:

```text
/api/stays/{id}/availability/?check_in=2026-12-20&check_out=2026-12-23&adults=2&children=1&rooms=1
```

Every requested night must satisfy inventory, blocking, occupancy, and minimum-stay
rules. Results contain nightly effective prices and totals; they do not create a
booking or payment. Stay and room/calendar writes require the direct owner,
assigned agent, active agency staff, or an administrator.

## Favourites and saved-search alerts

Authenticated users save either a property or stay through `GET/POST
/api/favourites/` and remove one with `DELETE /api/favourites/{uuid}/`. Add
`?type=property` or `?type=stay` to filter the dashboard list. Each result embeds
the corresponding compact listing card. Deleted listings cascade their favourites;
unpublished favourites remain in account history while ordinary public search still
excludes them. Public cards consistently expose `is_favourited` (`false` anonymously).

Saved-search CRUD is available at `/api/saved-searches/`, with current matches at
`GET /api/saved-searches/{uuid}/results/` and manual evaluation at `POST
/api/saved-searches/{uuid}/check/`. Criteria are validated JSON rather than fixed
columns. Property criteria support listing/property types, places, price/room
minimums, booleans, amenities, and bounds. Stay criteria support stay type, places,
prices, amenities, and occupancy preferences. Unknown keys, invalid choices,
negative values, malformed UUIDs, and inverted price ranges are rejected.

```json
{"search_type":"PROPERTY","name":"Ezulwini rentals",
 "criteria":{"listing_type":"RENT","town":"Ezulwini","min_bedrooms":2},
 "notifications_enabled":true,"frequency":"DAILY"}
```

Frequencies are `INSTANT`, `DAILY`, `WEEKLY`, and `OFF`; `OFF` disables
notifications. Evaluation uses the same domain query services as public search,
creates one `SearchAlertEvent` per newly discovered listing, and updates
`last_checked_at`. It sends no messages yet. The seeker dashboard summary is at
`GET /api/dashboard/seeker-summary/` and returns favourite, active-search, and new
alert counts.

## Messaging, guest enquiries, and property viewings

Persistent messaging is account-only and uses `Conversation`, unique
`ConversationParticipant` membership, and chronological `Message` records. A
marketplace conversation targets one property or stay; creating another active
thread for the same seeker and listing reuses the existing conversation. Listing
owners, assigned agents, and active agency staff can access their managed inboxes.

```text
GET/POST  /api/conversations/
GET/PATCH /api/conversations/{uuid}/
GET/POST  /api/conversations/{uuid}/messages/
POST      /api/conversations/{uuid}/mark-read/
DELETE    /api/messages/{uuid}/remove/
POST      /api/enquiries/guest/
```

Messages are returned oldest first. Send a thread with `{"property":"<uuid>",
"message":"Is this available?"}` or use `stay` and optionally
`BOOKING_ENQUIRY`. Send follow-ups with `{"body":"Hello","message_type":"TEXT"}`.
Sender identity always comes from the JWT. SYSTEM and viewing workflow messages are
server-generated. Deletion is soft and replaces the body with a neutral message.
Read state is stored per participant rather than per message.

Anonymous users can submit one-off, throttled guest enquiries with exactly one
listing and at least email or phone:

```json
{"property":"<uuid>","name":"Nomsa","email":"nomsa@example.com",
 "message":"Please contact me about this home."}
```

Property-only viewing requests create or reuse the seeker conversation and emit
workflow messages server-side:

```text
POST /api/properties/{uuid}/viewing-requests/
GET  /api/viewing-requests/
GET  /api/viewing-requests/{uuid}/
POST /api/viewing-requests/{uuid}/confirm/
POST /api/viewing-requests/{uuid}/decline/
POST /api/viewing-requests/{uuid}/cancel/
POST /api/viewing-requests/{uuid}/reschedule/
POST /api/viewing-requests/{uuid}/complete/
```

Creation accepts `requested_date`, `requested_time`, optional alternatives, and
notes. Requests must be future-dated, target a published property, not be made by
its owner, and not duplicate an active slot. Seekers cancel or request rescheduling;
authorized listing managers confirm, decline, or complete. No stay inventory,
booking, payment, WebSocket, notification-delivery, or WhatsApp integration is
performed in this phase.

## Stay bookings

Authenticated guests create reservations at `POST /api/stays/{stay_id}/bookings/`.
The room belongs to the URL stay; contact details, nightly prices, subtotal, taxes,
fees, total, and currency are snapshotted. Payments are not integrated, so new
bookings default to `UNPAID`. Optional `Idempotency-Key` headers safely reuse a
guest's prior submission.

`PENDING` and `CONFIRMED` consume inventory; declined, cancelled, completed, and
expired records do not. Creation runs atomically, locks the room and explicit
calendar rows, and subtracts active bookings for every night before inserting.
Pending holds expire after `BOOKING_HOLD_MINUTES` (default 30); run `python manage.py
expire_pending_bookings` manually until scheduling is introduced.

```text
GET /api/bookings/
GET /api/bookings/{uuid}/
POST /api/bookings/{uuid}/confirm/
POST /api/bookings/{uuid}/decline/
POST /api/bookings/{uuid}/cancel/
POST /api/bookings/{uuid}/complete/
GET /api/rooms/{uuid}/calendar/?start=2026-12-20&end=2026-12-31
```

Managers confirm, decline, and complete; guests may cancel. Valid transitions are
centralized. A booking creates or reuses its Stay conversation and server-generated
workflow messages. Capacity is multiplied by rooms booked, and price is nightly
effective price times room count. Taxes and fees remain zero behind explicit fields
for later policy. SQLite verifies the transaction logic but cannot reproduce
PostgreSQL row-lock concurrency; production `select_for_update` provides that guard.

## Notifications and background jobs

Notifications are durable, user-scoped records with allow-listed navigation data,
deduplication keys, read state, and preferences. Use `/api/notifications/`,
`/api/notifications/unread-count/`, mark-read actions, and
`/api/notification-preferences/me/`. Domain code calls the centralized service;
users cannot create notifications through the API.

Email uses a centralized provider boundary. Local development defaults to Django's
configured email backend, while production uses Bird's HTTP Email API with
`EMAIL_PROVIDER=bird`. Normal notification email is queued after transaction
commit and delivered by Celery; `EmailDelivery` keeps provider, status, attempts,
and Bird message IDs without storing rendered email bodies. `FRONTEND_BASE_URL`
continues to build account and reset links. Django templates under
`notifications/templates/emails/` provide the branded HTML and plain-text content;
preview them locally with `python manage.py preview_email <template_key>`. See
`docs/email.md` and `docs/email-templates.md` for setup, sender-domain
verification, retry behavior, and the distinction between Bird `accepted` and
final delivery.

Celery uses Redis in deployed environments while tests set eager mode. Scheduled
work evaluates saved searches (INSTANT means every 15 minutes by default), expires
booking holds, and reminds owners about stale property availability.

```powershell
celery -A Sureplace_back worker -l info
celery -A Sureplace_back beat -l info
```

Production requires the Django web service, PostgreSQL/PostGIS, Redis, a Celery
worker, Celery Beat, Bird email credentials, and a Bird-verified sending domain.
No SMS, push, WhatsApp, payment webhook, or WebSocket delivery is included.

## Verification and moderation

Authenticated users manage evidence requests at `/api/verification/requests/` and
upload PDF/JPEG/PNG documents while a request is still a draft. Documents are kept
outside the public media directory and are only downloaded through the authorized
endpoint. Required evidence is enforced on submission. Staff granted Django's
`verification.review_verificationrequest` permission review, approve, reject, or
suspend verification; every decision is audited and the applicant is notified.

Users report one property or stay at `/api/reports/listings/`. Duplicate open
reports are rejected. Staff review reports under `/api/moderation/reports/`, while
admins can pause, suspend, unpublish, or reinstate listings and view
`/api/moderation/summary/`. Destructive moderation decisions require reasons and
produce immutable audit records. Verification badges indicate evidence review,
not a SurePlace guarantee or endorsement.

## Frontend-ready API

The canonical prefix is `/api/v1/`; legacy `/api/` routes remain temporary aliases.
See `docs/api.md`, `docs/frontend-integration.md`, and `/api/v1/docs/`. Start local
dependencies with `docker compose up -d db redis`. Seed fictional data with
`python manage.py seed_demo_data`; reset requires `DEBUG=True` and `--reset --yes`.

## Production infrastructure

Production targets a Docker-based Render web service, Render PostgreSQL/PostGIS,
Render Key Value, separate Celery worker and Beat services, Cloudinary public media,
WhiteNoise static assets, and Bird transactional email. See
[`docs/render-deployment.md`](docs/render-deployment.md) for the architecture,
environment variables, deployment sequence, PostGIS verification, media security,
and smoke-test checklist. Local development continues to use filesystem storage;
set `USE_CLOUDINARY=true` only when Cloudinary credentials are configured.
