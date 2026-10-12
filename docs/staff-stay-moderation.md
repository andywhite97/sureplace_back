# Stay listing moderation

Staff Console → Stay Listings opens `/staff/stays`. The queue supports search,
status filters and pagination; each stay opens a review page with host identity,
location, stay/room photos, room inventory and pricing, amenities, booking policies,
reports and decision history. Staff with verification-review permission also get
direct links to each stay's submitted verification request and protected evidence.

Actions: start review, approve, request changes, reject, suspend, restore and add
an internal note. Approve/restore validate publication fields and active rooms.
Change requests, rejection and suspension require feedback. Owner notifications
and transactional email use the existing notification preferences and delivery
pipeline. Internal notes stay in the staff review record.

Approval publishes a listing; it does not automatically grant the separate
verified-stay badge. Evidence-based verification continues through the existing
verification queue.

## Rollout

1. Run `python manage.py migrate` on each deployment. Migration
   `stays.0007_alter_stay_options_alter_stay_status` introduces the changes-requested
   status and dedicated stay moderation permissions. Applied locally already.
2. In Access & Roles, assign `stays.review_stay` and the appropriate decision
   permissions to stay reviewers. Existing property-review permissions do not
   grant stay approval. Superusers have access automatically.
3. Hosts can edit and resubmit stays after requested changes or rejection.
4. Deploy frontend and backend together, then refresh the staff session to load
   updated permissions. The developer server was not running during the attempted
   browser preview; UI behavior was verified through automated component tests.

## API

`/api/v1/staff/stays/` exposes the queue and `summary/`; detail endpoints support
`start-review/`, `approve/`, `request-changes/`, `reject/`, `suspend/`, `restore/`,
`notes/` and `audit/`. Staff actions are atomic and lock the target row, so two
reviewers cannot silently approve the same submission. The legacy reinstate API
cannot publish a submitted stay or bypass the stay permissions/publication checks.

Validation: 61 moderation/stay/account tests pass on the isolated SQLite test
database; seven tests pass on native PostGIS (six stay moderation tests and the
concurrent last-room booking test). Frontend suite: 437 tests across 85 files pass.
