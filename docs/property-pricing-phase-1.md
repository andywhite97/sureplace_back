# Property pricing and entitlements — Phase 1

## Catalogue and API

The property app owns the catalogue; Angular reads it from
`GET /api/v1/pricing/properties/`. Monetary fields are `DecimalField` values,
serialized as decimal strings, in SZL with display symbol E. The migration seeds:

| Plan | Monthly price | Total base live allowance | Accounts |
| --- | --- | --- | --- |
| Individual Free | E0 forever | 2 | Individual |
| Agency Free | E0 forever | 5 | Agency |
| Starter | E149 | 10 | Individual / agency |
| Professional | E349 | 25 | Individual / agency |
| Agency Plus | E699 | 75 | Agency |

`SINGLE_EXTRA` is E49 for one unit; `TRIPLE_EXTRA` is E129 for three units.
Each activates for 90 days. Plans/packages are configurable in Django admin.
Package duration and amount are captured on each granted unit, so later catalogue
changes do not rewrite its purchase history. All core property functionality is
included in free plans. Property sales commissions are 0%.

`GET /api/v1/account/property-entitlements/` is authenticated and defaults to the
individual account even if the user also belongs to an agency. `?agency=<uuid>`
requires an active agency membership (staff may inspect any agency). The optional
`?property=<uuid>` is scoped to that same owner and returns `can_publish_property`,
including reuse of the property's own unexpired assigned allowance. Foreign
properties are not exposed.

The summary includes current plan, live count, base allowance, active/unused extras,
remaining capacity, display limit, usage percentage, legacy over-limit state,
subscription status/expiration/grace boundary, and activated-unit expiry dates.
Only unused units can increase capacity for another property. A bound unit stays
with its property when paused or made unavailable. The display limit includes
extras currently covering live properties; the list of active extras also includes
temporarily hidden assigned properties.

## Enforcement and publication

The existing public search condition is the slot condition:
`status=PUBLISHED AND availability_status=AVAILABLE`. Draft/review, paused,
expired, rejected, suspended and unavailable records do not consume slots. Sold
and rented inventory uses the existing mark-unavailable action. Deleted ordinary
properties no longer count; properties with entitlement history are protected
from hard deletion and may be paused/hidden to preserve the ledger.

Explicit `PropertyListing.agency` selects agency capacity shared across every
agent. Otherwise `PropertyListing.owner` selects personal capacity. There is no
new account, membership or permission hierarchy.

`properties.entitlements` centralizes the rules. Every model save takes a
transaction and locks the existing User or Agency row. Owner transfers lock both
scopes in a consistent order. The persisted state and `update_fields` determine
whether a save enters public inventory; ordinary live edits retain their slot.
This covers approval, restoration, admin saves, direct ORM saves, availability
confirmation and ownership transfers. Quota-affecting queryset updates,
`bulk_update` and `bulk_create` are rejected: bulk publication must iterate model
saves in a transaction. Raw SQL is an administrative database operation and is
outside application enforcement.

Submission performs a preflight but does not reserve a live slot or start an extra
unit's clock while review is pending. Approval checks again; only actual entry into
public inventory allocates an unused, server-granted unit. Concurrent approvals
cannot consume the same final slot or activate the same unit twice. Drafts remain
editable at full capacity. Paused/expired properties may be resubmitted through
the existing review workflow.

Capacity errors use HTTP 400, code `PROPERTY_LISTING_LIMIT_REACHED`, an explanatory
message, integer counts and `upgrade_available`, alongside the existing `errors`
and `request_id` envelope. Agency members who have been deactivated cannot manage
agency properties through a lingering owner reference.

## Grants, renewal and payment safety

There are no public subscription/add-on mutation or payment-success endpoints.
Catalogue prices are informational; `checkout_available` is false. The reserved
`PROPERTY_PURCHASES_ENABLED` feature flag defaults false; turning it on alone
does not enable checkout. A future provider-neutral verified payment adapter and
working server-side workflow are also required. Phase 1 does not synthesize
transactions, take payment, auto-renew, or trust client payment declarations.

Staff with the corresponding Django model permissions can grant paid access:

1. In **Property subscriptions**, choose exactly one Account or Agency, an
   applicable Plan, dates, ACTIVE status and a grant reason. The staff actor/time
   are recorded. Optional provider and transaction references prepare for future
   verified payment integrations. A single ACTIVE subscription per owner is
   enforced by the database. Cancel the previous subscription before creating a
   replacement; renewal edits to its dates are recorded by Django admin history.
2. In **Property listing add ons**, choose exactly one Account or Agency, a source
   package and a reason. Saving creates the full package: one auditable row per
   unit, with shared purchase reference, unique unit ordinal and exact amounts
   summing to the package price. Unused units have no activation/expiration date.
3. Renewal of an expired extra allowance means granting a new package/unit, then
   resubmitting the paused property for review. The old unit remains in history;
   it cannot be reassigned or extended. Activation/expiration/owner/package/
   amount/reason history becomes immutable after activation. Admin has read-only
   access to existing extra units and no grant deletion action.

Admin grants represent documented authorization, not proof that a payment was
received. Record the actual offline arrangement or grant reason. Only a future
verified server-side confirmation should activate online paid purchases.

## Migration and expiry policy

`0007_propertyaddonpackage_propertyplan_and_more` creates PropertyPlan,
PropertyAddOnPackage, PropertySubscription and PropertyListingAddOn, including
exactly-one-owner checks, active subscription uniqueness, one active assigned
unit per property, purchase-unit uniqueness, nonnegative amount and valid-date
constraints. `0008_property_pricing_catalogue` seeds catalogue rows without
modifying existing property rows. It does not migrate Stay data.

Existing over-limit live inventory is preserved and exposed as
`legacy_over_limit`. New publication/re-entry requires capacity. Paid plans replace
the free base allowance; free limits are not added to paid limits.

`PROPERTY_SUBSCRIPTION_GRACE_DAYS` defaults to **7 days**. An expired subscription
retains paid base capacity during grace. Afterwards new publications use the free
plan; existing published properties remain live. Cancellation/downgrade has the
same preservation behavior. There is no subscription-triggered mass unpublication
or deletion. Staff should review over-limit inventory and arrange renewal or
planned pauses with the account. Phase 1 intentionally favors preservation.

Celery beat runs `properties.tasks.process_property_entitlements` hourly. It
expires each due active unit and recomputes ordinary capacity under the owner lock.
If ordinary capacity covers its property, the listing stays live; otherwise only
that specific extra listing is paused. Photos, conversations, viewings and ledger
history remain. Stable existing notification event keys prevent duplicate
7-day/1-day reminders and expiration notices. The task uses `notify_transactional`
and `listing_reminders_email`, respecting existing in-app/email preferences and
robust delivery handling. Re-running the task changes no already-expired unit.
An unused unit may have an optional `activate_before` date from package
`purchase_validity_days`; otherwise it remains available until activated.

## Deployment and checks

Apply the property migrations before deploying the updated application:

```powershell
python manage.py migrate properties
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test properties.tests_entitlements properties.tests moderation.tests agencies.tests verification.tests messaging.tests core.tests --settings=properties.test_settings --noinput
python scripts/test-property-postgres.py
```

The PostgreSQL helper uses only a local `.env` DATABASE_URL, creates a uniquely
named test database, and deletes that test database at the end. It prints no
credentials. JSON location test mode focuses this suite on real PostgreSQL row
locks and constraints; it is not a PostGIS geometry integration test. SQLite skips
the two row-lock race tests, which are executed by the PostgreSQL helper.

Frontend checks (from the Angular directory):

```powershell
npm test -- --watch=false
npm run build:prod
```

Changes to Stay, RoomType, StayBooking, accommodation availability and stay pricing
are outside this implementation. Existing Stay pricing tab behavior is retained.

## Delivery inventory

Backend files modified:

- `.env.example`
- `Sureplace_back/api_urls.py`, `Sureplace_back/settings.py`
- `core/exceptions.py`, `moderation/views.py` (property paths only)
- `properties/admin.py`, `properties/models.py`, `properties/permissions.py`,
  `properties/serializers.py`, `properties/services.py`

Backend files added:

- `properties/entitlement_models.py`, `properties/entitlements.py`
- `properties/pricing_admin.py`, `properties/pricing_views.py`, `properties/tasks.py`
- `properties/migrations/0007_propertyaddonpackage_propertyplan_and_more.py`
- `properties/migrations/0008_property_pricing_catalogue.py`
- `properties/tests_entitlements.py`, `properties/test_settings.py`
- `scripts/test-property-postgres.py`, `docs/property-pricing-phase-1.md`

Frontend files modified:

- `src/app/features/public-pages.component.ts` (property pricing branch)
- `src/app/features/manage/property-form.component.ts` and its `.spec.ts`
- `src/app/features/manage/property-management-list.component.ts` and its `.spec.ts`

Frontend files added:

- `src/app/core/api/property-entitlements-api.service.ts` and its `.spec.ts`
- `src/app/features/property-pricing.component.ts` and its `.spec.ts`
- `src/app/features/manage/property-capacity.spec.ts`

Pre-existing unrelated working-tree changes were retained, including Stay work.
Test logs and the isolated preview database are local QA artifacts, not source files.

## Executed validation — 11 October 2026

| Check | Result |
| --- | --- |
| Django system checks | Passed, no issues |
| Migration consistency | Passed, no changes detected |
| Backend entitlement and domain regressions | 115 tests run: 113 passed, 2 PostgreSQL-only races skipped in SQLite |
| PostgreSQL entitlement suite | 26 tests passed, including both row-lock races; no skips |
| Angular complete test suite | 89 files, 458 tests passed |
| Angular production build | Passed |
| New Python modules, Ruff | Passed |
| Browser layout | Five desktop columns; stacked mobile cards at 390px; no page horizontal overflow at that width |

Backend regressions exercised existing property CRUD, approval/restoration,
verification, search, messages and viewing requests. The PostgreSQL helper created
and removed its own uniquely named local test databases. Preview migrations were
applied only to an isolated QA SQLite database, not to the application's database.
Apply `python manage.py migrate properties` to the application database and restart
the existing Celery workers/beat when releasing this change.

The production build still reports existing style-budget warnings in other
components and can fall back to client rendering when remote dynamic-route
discovery times out. The property's new style bundle is within budget. The
shared app has an existing global 320px minimum body width; narrow desktop
emulation with a reserved scrollbar can overflow below that minimum. This shared
rule was not changed, since it affects Stay and other pages. Existing light-only
theme variables and component patterns were retained.

Final logs: `.booking-qa/property-pricing-backend-final.log`,
`.booking-qa/property-pricing-postgres.log`, and the Angular directory's
`tmp/property-pricing-tests.log` / `tmp/property-pricing-build.log`.
Browser screenshots are in the Angular directory's
`tmp/property-pricing-mobile.png` and `tmp/property-pricing-desktop.png`.

Immediately available after release: free catalogue/allowances, draft editing,
shared quotas, admin grants, automatic allocation of valid grants, guarded
publication, scheduled expiry/reminders, pricing UI and dashboard summaries.
Payment-dependent checkout, online purchases, verified gateway activation,
recurring charges and automatic renewal remain disabled.
