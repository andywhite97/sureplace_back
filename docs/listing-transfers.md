# Listing ownership transfers

The account navigation and property/stay management pages link to `/account/transfers`.
An individual listing owner or an active owner/admin of its managing agency can send
one pending transfer request per listing. Targets are existing active users (email)
or active agencies. An agency owner/admin accepts for the agency; ordinary agents
cannot initiate or accept transfers. Participants must verify their email before
using the endpoints.

Requests expire after seven days. Senders can cancel; recipients can decline.
Acceptance rechecks current ownership and the sender's authority, locks source and
destination entitlement scopes and the listing, and changes ownership atomically
with the transfer audit record. Agency acceptance assigns the accepting admin as
the accountable owner. The previous agent assignment is cleared, and verification
resets to UNVERIFIED. Listing content, IDs, slugs, publication status, media and
booking records remain attached to the listing. This does not migrate historical
private conversations or reassign their participants.

Publication capacity remains enforced through the existing model save path.
Existing safeguards block changes of entitlement owner for listings with paid
add-on history. Failed acceptance preserves both ownership and the pending request.
These listings need support to resolve their entitlement commitments first.
Ordinary listing edits cannot change an existing listing's managing agency.

API (under `/api/v1/`, also available under `/api/`):

- GET `/listing-transfers/options/`: authorized listings and active receiving agencies.
- GET `/listing-transfers/`: latest 200 requests visible to the sender, user recipient,
  or current receiving-agency owners/admins. Expired pending requests display EXPIRED.
- POST `/listing-transfers/`: `{kind: "property"|"stay", listing_id, email}` or
  `{kind, listing_id, agency_id}`. Exactly one destination is required.
- POST `/listing-transfers/{id}/`: `{action: "accept"|"decline"|"cancel"}`.

Requests and outcomes create in-app system notifications. No email delivery is
added by this feature. The stored audit record includes original owner and agency,
sender, destination, expiry, resolution time and resolving user. Expired requests
are closed when a new request is sent for the listing.

Deploy the migration with `python manage.py migrate` before serving the new API.
Run `python manage.py test core.tests_transfers` for the transfer API tests.
Production row locking needs PostgreSQL; SQLite tests verify behavior and rollback,
not concurrent database locking.
