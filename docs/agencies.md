# SurePlace Agencies

Agency management is optional. Users can still list independently as owners or
hosts; creating an agency adds a supply-side organization and team capability.

## Existing Architecture

SurePlace uses:

- `Agency` for the organization profile and verification status.
- `AgentProfile` for the user-to-agency relationship.

No permanent `User.role` is used. A user can browse, list independently, own an
agency, or act as an agency member at the same time.

## Roles

`AgentProfile.role` represents the membership capability:

- `OWNER`: full agency control.
- `ADMIN`: agency profile, team, listings and enquiries management.
- `AGENT`: team member for agency listing/enquiry work.

The first agency creator becomes `OWNER` in the same transaction as agency
creation. An agency cannot be left without an active owner.

## Creation Flow

Frontend route:

```text
/account/manage/agency/create
```

API endpoint:

```text
POST /api/v1/agencies/
```

Email verification is required server-side. Unverified users receive a structured
`403` with code `email_not_verified`.

Agencies start active and unverified. Agency creation does not imply:

- verified agency
- verified agent
- verified property
- verified stay

## Management Routes

Private Angular routes are CSR only:

- `/account/manage/agency`
- `/account/manage/agency/create`
- `/account/manage/agency/profile`
- `/account/manage/agency/team`
- `/account/manage/agency/listings`
- `/account/manage/agency/enquiries`
- `/account/manage/agency/verification`
- `/account/manage/agency/settings`

Listings, enquiries, bookings, messages and verification reuse existing SurePlace
systems rather than introducing duplicate workflows.

## Invitations

Owners/admins invite by email and intended role:

```text
POST /api/v1/agencies/{id}/invitations/
POST /api/v1/agency-invitations/accept/
POST /api/v1/agency-invitations/decline/
```

Invitation tokens are persisted, dedicated to agency invitations, expire, and are
single-use. They do not reuse password reset, email verification, or JWT tokens.

Invited users must consent by accepting. Existing users must be authenticated and
email-verified before membership activates.

## Verification

Agency verification uses the existing verification system with type `AGENCY`.
Verification scope remains precise: a verified agency badge only describes the
agency, not its agents, properties, or stays.

## Known Limitations

Ownership transfer and destructive agency deletion are intentionally not included
yet. Both need explicit product rules to avoid orphaned listings or ownerless
agencies.
