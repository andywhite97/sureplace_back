# Demo Data

`python manage.py seed_demo_data` creates a deterministic SurePlace dataset for local development, staging, QA, and product demos. It must not be wired into production deploy/start commands.

## Usage

```bash
USE_SQLITE=true DEBUG=true python manage.py seed_demo_data --reset
USE_SQLITE=true DEBUG=true python manage.py seed_demo_data
USE_SQLITE=true DEBUG=true python manage.py seed_demo_data --count 100 --seed 2026
```

Default behavior creates approximately 50 primary listings with a 60/40 split:

- 30 properties
- 20 stays

`--count` changes the primary listing target while preserving the same rough ratio. `--seed` makes location offsets and amenity selection deterministic. `--reset` deletes only demo-tagged/demo-owned data, then recreates it.

## Safety

Demo records are marked by:

- email domain: `@demo.sureplace.local`
- listing slugs beginning with `demo-`
- agency slugs beginning with `demo-`
- deterministic notification/event keys beginning with `demo-`

Reset does not call `Model.objects.all().delete()` and does not target real production users or listings. Outside `DEBUG`, `--reset` also requires `--yes`.

The command does not call Bird, does not enqueue Celery tasks, and does not require Redis. It creates in-app notifications directly and leaves `EmailDelivery` empty for seeded demo users.

## Demo Login

The shared demo-only password is:

```text
SurePlaceDemo2026!
```

The command prints one demo login when `DEBUG=True` or when `--show-credentials` is passed:

```text
seeker1@demo.sureplace.local
```

Do not reuse this password outside local/staging demo environments.

## What Gets Created

Default seed creates:

- 12 users across seeker, owner, host, agent, mixed staff, and reviewer roles
- 4 fictional agencies
- 5 agent profiles
- 30 property listings, usually 24 public and 6 lifecycle variants
- 20 stay listings, usually 16 public and 4 lifecycle variants
- room types and 90 days of room availability
- 3 to 6 gallery images per property and stay
- room images for room-type cards
- favourites, saved searches, search alert events
- viewing requests across multiple statuses
- bookings across all booking statuses
- conversations, user messages, system messages, and varied read states
- in-app notifications across common notification types
- verification requests across identity, agent, agency, property, and stay scopes
- moderation reports

The core Explore Eswatini locations are represented with public data:

- Mbabane
- Manzini
- Ezulwini
- Matsapha
- Lobamba
- Siteki

Additional demo locations include Malkerns, Nhlangano, Piggs Peak, and Big Bend.

## Images

Seeded media uses bundled deterministic placeholder image bytes written through Django storage. No image URLs are scraped, no remote image download is required, and local seeding does not require Cloudinary credentials. In staging with Cloudinary enabled, normal storage settings handle these files.

Every public property and stay receives exactly one cover image plus an ordered gallery.

## Coordinates

Every public property and stay has realistic Eswatini coordinates near its town. SQLite mode stores the existing JSON-style latitude/longitude fallback. PostGIS mode stores `Point(longitude, latitude, srid=4326)`.

Small deterministic offsets prevent every marker from sitting on the exact town centre, so map clustering, bounds search, and "search this area" flows have useful spatial spread.

## Verification Scopes

The dataset intentionally separates verification scopes:

- verified agent with an unverified property
- verified agency with verified and unverified listing examples
- verified property owned by a private owner
- pending identity verification
- rejected property/agency verification

Verified Agent does not imply Verified Property, and Verified Agency does not imply Verified Stay.

## Troubleshooting

`no such table` errors: run migrations first.

```bash
USE_SQLITE=true DEBUG=true python manage.py migrate --noinput
```

Counts changed after using `--count`: run the next count change with `--reset`.

Images accumulate in local media storage: database rows remain idempotent, but old media files can remain on disk because Django storage does not delete files automatically in every backend.
