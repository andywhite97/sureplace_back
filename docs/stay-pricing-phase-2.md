# Stays pricing and entitlements — Phase 2

## Architecture and ownership

Property and Stay catalogues, subscriptions, grants and capacity queries remain
independent. Phase 1 plan codes, prices, allowances and public API payloads are
unchanged. Shared internal mechanics now live in `core/entitlement_utils.py`,
`core/entitlement_models.py` and `core/entitlement_admin.py`: owner row locks,
exactly-one-owner constraints, Decimal package splitting, grant audit fields and
admin actor binding. Property modules retain their existing import surfaces.

The inspected Stay model already has `owner`, optional `agency`, and optional
`agent` relationships. Explicit `Stay.agency` selects the existing agency/team
scope, shared across its managed establishments. Otherwise `Stay.owner` selects
the individual host. No new agency, company, account or permission hierarchy was
introduced. Plans apply to either existing scope; Host Free is two stays per
individual or team. Existing Stay management permissions are retained.

Changing the responsible user within the same agency preserves that agency's
entitlement scope and assigned unit. Financial-scope transfers validate destination
capacity. Serializer updates reload and lock current ownership/status, so a stale
edit cannot reverse a moderation pause or an ownership transfer.

`stays.entitlements.consumes_slot()` maps **PUBLISHED** to one active stay slot.
DRAFT, SUBMITTED, UNDER_REVIEW, CHANGES_REQUESTED, PAUSED, REJECTED and SUSPENDED
are excluded. A sold-out published stay still counts. Room types, quantities,
availability rows and bookings are never independently counted or limited.

## Catalogue, models and migration

| Plan | Price | Total base active stays |
| --- | --- | --- |
| HOST_FREE — Host Free | E0 forever | 2 |
| HOST_PRO — Host Pro | E199/month | 5 |
| BUSINESS — Business | E449/month | 15 |
| ENTERPRISE — Enterprise | E899/month | 30 |

Paid allowances replace the free base allowance. All essential existing hosting
features remain available on all plans: listing/images, rooms, calendars, nightly
prices, enquiries, bookings, management, messaging, verification and notifications.

`SINGLE_STAY_EXTRA` is E79 for one unit; `TRIPLE_STAY_EXTRA` is E199 for three.
Each unit activates independently for 90 days when assigned. Unused units have no
activation/expiry time; optional package `purchase_validity_days` is snapshotted
as `activate_before`. Price snapshots use Decimal amounts; three units sum exactly
to E199 (E66.33, E66.33 and E66.34). No frontend amount is authoritative.

`STAY_BOOST_7D` is an informational E59/seven-day promotion. Existing featured
flags lack an audited timed promotion/ranking lifecycle, so boosting is **not
operational**. No ranking changes, impressions, engagement or additional capacity
are synthesized. Its admin entry is read-only and checkout is unavailable.

New models:

- StayPlan, StayAddOnPackage and StayPromotion: configurable catalogue.
- StaySubscription: exactly one owner scope; plan and price snapshot; ACTIVE,
  GRACE, EXPIRED or CANCELLED status; start/expiry/grace dates; recorded grace
  entry/expiration; staff actor, reason and provider-neutral references.
- StayListingAddOn: independent purchase unit, owner scope, package, price and
  duration snapshots, assignment/activation/expiry, processing timestamp and audit.
- StayCapacityReview: explicit PROTECTED_BOOKINGS, OVER_LIMIT or RESOLVED state
  per affected stay, reason, optional expired unit, timestamps and whether that
  specific add-on expiry may pause the stay once safe. State changes also use the
  existing ModerationAuditEvent history.

Migration `0008_stayaddonpackage_staylistingaddon_staycapacityreview_and_more`
adds these tables and constraints. `0009_stay_pricing_catalogue` seeds the four
plans, two packages and boost. Both are additive. Catalogue migration does not
write existing Stay, RoomType, RoomAvailability, Booking or Property records or
rewrite their identifiers. It depends on the pre-existing Stay moderation
migration `0007_alter_stay_options_alter_stay_status` already in the working tree.

Constraints include exactly one account/agency owner, one active/grace subscription
per scope, one active assigned unit per stay, unique purchase-reference/ordinal,
valid activation/subscription/grace dates, nonnegative amounts, positive package
units/durations and disabled auto-renewal. Purchase/grant snapshots are immutable;
activated units cannot be reassigned or extended. A stay with entitlement history
cannot move to another entitlement owner. Ordinary transfers check destination
capacity under both owner locks. Public PATCH cannot set publication or grants.

## Publication, locking and booking safety

Stay model saves centrally enforce initial publication, approval, restoration,
paused re-entry, direct ORM changes and ownership transfers. Existing live edits
remain possible at capacity. Quota-changing queryset updates, bulk update and bulk
creation are rejected; a legitimate bulk publication must iterate model saves in
a transaction. Admin validation gives field errors at capacity. Submission checks
capacity without reserving a slot or starting an add-on clock during review;
approval performs a fresh check and allocation at actual publication.

Owner locks use PostgreSQL **NO KEY UPDATE**, which serializes publications while
allowing booking/conversation foreign keys to the host. SQLite test mode does not
claim row-lock guarantees. Transfers acquire source/destination scope locks in
stable order. Moderation and submission acquire owner locks before the Stay row.

Booking creation now explicitly locks **RoomType, then Stay**, and re-reads the
current publication state after waiting. Entitlement expiry takes **owner, rooms
in primary-key order, then Stay**, before checking obligations. Stay admin room
inlines take the same room-before-stay order. Existing booking calculations,
idempotency, prices, hold duration, transitions and cancellation rules are unchanged.

Expiry performs no writes to Booking, BookingEvent, RoomType, RoomAvailability,
room images, Stay images or booking-linked conversations:

1. Expire the specific unit and recalculate ordinary plan coverage.
2. If ordinary capacity or a newer valid unit covers the stay, keep it live.
3. Otherwise inspect PENDING holds that have not reached their existing expiry,
   and CONFIRMED reservations with check-out on or after the current local date.
   Check-out day is protected conservatively. A null pending expiry also remains
   protected until the existing booking workflow resolves it.
4. With obligations, keep the stay PUBLISHED, record PROTECTED_BOOKINGS, notify the
   host/team, and request renewal or admin review. New booking workflows remain
   available; no new booking-blocking policy is introduced.
5. Only a specific expired add-on stay with no outstanding obligations may become
   PAUSED. All references, calendars, inventory, rooms, prices and history remain.
6. Revisit protected extra stays on later runs. After booking obligations finish,
   normal safe pausing may occur unless capacity or renewal now covers the stay.

Pending bookings retain the existing expiry task and rules. Guest/host booking
detail, management, confirmations, messaging and cancellation remain available.
Renewal does not mutate the old grant, cancel reservations or reset room inventory.

Grandfathered and subscription/downgrade over-limit inventory is preserved. The
task records review/protection states and notifies; it does **not** mass-pause it.
Additional publication is blocked while ordinary inventory exceeds base capacity.
Unused units do not hide this over-limit state; staff can allocate trusted units
to existing stays or grant a sufficient plan to resolve it explicitly.

## Grace, grants and notifications

`STAY_SUBSCRIPTION_GRACE_DAYS` defaults to seven. The boundary is stored when the
subscription is granted. During grace paid base capacity remains; the task records
GRACE and `grace_entered_at` and sends a stable-key notice. After grace it records
EXPIRED/`expired_at`, applies Host Free for new capacity, and preserves published
inventory and all reservations. Cancellation immediately uses free capacity with
the same inventory preservation policy. To change plan/renew, cancel the old
active subscription and create an audited replacement rather than rewriting its
financial/date snapshot.

Django admin exposes catalogue configuration, subscriptions, package grants and
read-only capacity reviews. Paid grants require an active staff actor with the
corresponding `stays.add_staysubscription` or `stays.add_staylistingaddon` permission
and a reason. Existing historical grants can expire safely after the original
staff member leaves. No public paid activation endpoint exists.

Creating an add-on in admin grants the whole selected package, one row per unit,
with common purchase reference and independent unit ordinal. For a protected live
stay, first grant a package to its actual owner/team, then use **Allocate a granted
extra unit to renew selected stays** in Stay Capacity Reviews. Allocation additionally
requires `stays.change_staylistingaddon`. It uses only matching unused units and is
idempotent. Paused stays can be resubmitted through normal review after a new grant.

Celery beat runs `stays.tasks.process_stay_entitlements` hourly. Seven-day,
one-day, expiration, grace, over-limit and protected-reservation notices use the
existing `notify_transactional`, stable event keys and `listing_reminders_email`
preferences. No parallel email delivery infrastructure is added.

## APIs and Angular

- `GET /api/v1/pricing/stays/`: SZL/E catalogue, Decimal strings, plans, base limits,
  add-ons, unavailable promotion, core features, checkout=false and commission=0%.
- `GET /api/v1/account/stay-entitlements/`: authenticated personal summary by
  default; `?agency=<uuid>` checks existing team membership. Optional `?stay=<uuid>`
  uses existing Stay management authorization and the stay's authoritative scope;
  a supplied agency must match. Foreign unmanaged stays are rejected.

Summary includes current plan/status, active count, base/extra/unused units,
remaining capacity, effective display limit, backend usage percentage, scoped
`can_publish_stay`, legacy/protected over-limit flags, subscription/grace dates,
activated-unit expirations and capacity review records. Domain errors use HTTP 400
and `STAY_LISTING_LIMIT_REACHED`, with typed counts/capacity and the existing
`errors` / `request_id` envelope.

The existing pricing selector has an independent Stays component. Dashboard and
form links use `/pricing?section=stays`, with `#extra-stays` where relevant. Plan
cards, comparison table, add-ons and boost prices come from the backend. Host Free
is teal-highlighted. Paid actions honestly say coming soon. FAQs explain rooms,
capacity, expiry, booking safety, commission and future upgrades.

The existing Stay dashboard shows backend plan/usage/progress, renewal/grace and
protected review notices; it refreshes on load and publication status changes.
Role-based/seeker-only navigation remains unchanged. The existing form saves and
rehydrates the draft/images/room data before preflight. Full capacity/server races
retain the form and show pricing options. Published editing saves without
resubmission; paused stays can return through review.

## Payment and promotion limitations

`STAY_PURCHASES_ENABLED` defaults false. Enabling it alone cannot enable checkout:
Phase 2 has no verified gateway workflow, no online money collection, simulated
transactions or frontend payment-success acceptance. Provider/reference fields
prepare for verified server confirmation later. Admin grants represent documented
authorization, not proof of payment. Automatic renewal remains false at model and
database levels. Booking commission stays 0%; existing booking price calculations
are unchanged. Boost is a read-only future catalogue product.

## Production release

No production migrations were applied by this task. Obtain explicit deployment
approval before running migrations on the live production database.

1. Review the combined working tree and deploy the backend before the frontend.
2. Back up production and review the migration plan, including the already-existing
   Stay moderation `0007` and any pending Phase 1 property migrations.
3. Apply `python manage.py migrate` after approval. Schema/catalogues must be ready
   before accepting writes with the new model save guards.
4. Run system checks and confirm the two public catalogues and authenticated
   summaries against individual/team accounts. Keep both purchase flags false.
5. Give approved staff the appropriate Django grant/review permissions.
6. Restart existing Celery workers/beat so the hourly Stay task is registered.
7. Deploy the validated Angular production output and review protected/legacy
   account notices. Arrange renewals with hosts; no mass unpublication is required.

Repository validation commands:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test stays.tests_entitlements stays.tests bookings.tests_booking bookings.tests_concurrency moderation.tests_stays moderation.tests properties.tests_entitlements properties.tests agencies.tests verification.tests messaging.tests core.tests --settings=stays.test_settings --noinput
python scripts/test-stay-postgres.py
# From the Angular directory:
npm test -- --watch=false
npm run build:prod
```

`stays.test_settings` uses the existing isolated JSON-location mode, local caches,
MD5 test passwords and locmem email. Test-only post-migrate hooks reseed catalogues
after TransactionTestCase flushes; production never uses these hooks. The
PostgreSQL helper refuses non-local database hosts and creates/removes a uniquely
named test database without printing credentials. It verifies real SQL row locks,
not PostGIS geographic calculations.

## Executed validation (11 October 2026)

| Check | Result |
| --- | --- |
| Django system checks | Passed, no issues |
| Migration consistency | Passed, no changes detected |
| Broad backend regression suite | 209 tests: 201 passed, 8 PostgreSQL-only skips |
| Isolated PostgreSQL suite | 64 passed, no skips; includes booking and shared-account quota races plus Phase 1 entitlements |
| Angular full suite | 92 files, 470 tests passed |
| Angular production build | Passed; existing component style-budget warnings remain |
| Ruff and Git whitespace checks | Passed for the checked implementation files |
| Responsive browser checks | Unverified: in-app browser repeatedly timed out while binding the preview tab |

The first Angular run had worker startup timeouts in two existing test files and
was not counted as successful. The full suite then passed with a temporary local
single-worker configuration, without exclusions:

```powershell
npm test -- --watch=false --runner-config=tmp/stay-vitest-single-worker.ts
```

That ignored configuration sets `maxWorkers: 1` and `testTimeout: 15000` through
Vitest's `defineConfig`. Layout source includes four desktop columns, two below
900px and stacked cards below 600px, but this is not a substitute for visual
verification. Browser automation timed out on its focus-emulation command before
DOM/screenshot access; no screenshot or measured viewport result is claimed.

All database execution used isolated test databases or the dedicated preview
SQLite file `.booking-qa/stay-pricing-preview.sqlite3`. No live production
migrations were applied. Local test/build logs are retained under `.booking-qa/`
and `tmp/`. PostgreSQL tests exercise real locks using JSON-location test mode;
PostGIS geographic behavior is outside this change's validation scope.

## File inventory

Created backend files: `core/entitlement_utils.py`, `core/entitlement_models.py`,
`core/entitlement_admin.py`, `stays/entitlement_models.py`, `stays/entitlements.py`,
`stays/pricing_admin.py`, `stays/pricing_views.py`, `stays/tasks.py`,
`stays/tests_entitlements.py`, `stays/test_settings.py`, the Stay `0008` / `0009`
migrations, `scripts/test-stay-postgres.py` and this document.

Modified backend files: `properties/entitlement_models.py`, `properties/entitlements.py`,
`properties/pricing_admin.py` (shared internal utilities only); `stays/models.py`,
`stays/services.py`, `stays/serializers.py`, `stays/admin.py`; `bookings/services.py`
(lock order/fresh-state read only); `moderation/stays.py`, `moderation/views.py`;
`core/exceptions.py`, `Sureplace_back/api_urls.py`, `Sureplace_back/settings.py`,
`.env.example`.

Created frontend files: `src/app/core/api/stay-entitlements-api.service.ts` and its
spec; `src/app/features/stay-pricing.component.ts` and its spec;
`src/app/features/manage/stay-capacity.spec.ts`.

Modified frontend files: `src/app/features/public-pages.component.ts` (Stays branch
and section selection), `src/app/features/manage/stay-management-list.component.ts`,
`src/app/features/manage/stay-form.component.ts` and its spec. Pre-existing unrelated
changes were preserved.

Local QA logs/previews are under the backend `.booking-qa/` and Angular `tmp/`
directories and are not release source files.
