# API contract

`/api/v1/` is canonical; `/api/` temporarily aliases the same views. OpenAPI is at
`/api/v1/schema/`, Swagger at `/api/v1/docs/`, and ReDoc at `/api/v1/redoc/`.
JWT endpoints live under `auth/`; refresh tokens rotate and logout revokes them.
Collections use `count`, `next`, `previous`, and `results`; `page_size` defaults to
20 and is capped at 100.

Errors contain `code`, `message`, field-level `errors`, and `request_id`. Responses
return `X-Request-ID`. Public bootstrap data is at `config/` and `reference/`. UUID
resources return 403 or 404 according to whether existence can safely be revealed.

## Stay bookings

Stays expose `booking_mode` (`REQUEST_TO_BOOK`, the default, or `INSTANT_BOOK`),
`cancellation_policy` and `house_rules`. Managers edit them through the existing
Stay update endpoint. Room types retain their existing nightly rates, quantity,
occupancy and minimum-stay rules.

`GET /stays/{id-or-slug}/availability/` accepts `check_in`, `check_out`, `adults`,
`children`, `rooms` and optional `include_unavailable=true`. Each room result
includes `available`, `rooms_available`, `nightly_prices`, `total`, `minimum_stay`
and `reason` (`occupancy`, `minimum_stay`, `inventory`, or null). Dates are
check-in inclusive and check-out exclusive. Public responses contain no guest data.

`POST /stays/{uuid}/bookings/` requires an authenticated, verified guest and:

```json
{
  "room_type": "<room UUID>",
  "check_in": "2026-12-20",
  "check_out": "2026-12-22",
  "adults": 2,
  "children": 0,
  "rooms": 1,
  "guest_name": "Andile Hlophe",
  "guest_email": "<signed-in account email>",
  "guest_phone": "+26876936838",
  "special_requests": "",
  "policies_accepted": true,
  "expected_total": "1800.00"
}
```

Send `Idempotency-Key` (at most 100 characters) and retain it across retries.
`expected_total` is an optional optimistic quote check, never an authoritative
price. A changed price returns HTTP 409 with `code=price_changed`, `new_total`
and `nightly_prices`; the guest must review and accept it before retrying.
The server checks current inventory, snapshots nightly prices/policies and returns
the Booking. Request mode creates `PENDING` with the platform expiry; instant
mode creates `CONFIRMED` with no pending expiry. Payment is `PAY_AT_PROPERTY`.

Booking list/detail support `scope=guest` or `scope=manager`, and list filters
`stay`, `room_type`, `status`, `payment_status`. A list `idempotency_key` lookup
is always restricted to the signed-in guest, allowing recovery after a lost
submission response. All list pages must be read for aggregate dashboard counts.

Existing `/bookings/{uuid}/confirm/`, `/decline/`, `/cancel/`, `/complete/`
actions remain authoritative. Decline requires `reason` from `NO_AVAILABILITY`,
`CANNOT_ACCOMMODATE`, `PROPERTY_UNAVAILABLE`, `OTHER`, with optional `note`.
Operator cancellation requires a reason; guest cancellation has an optional reason.
Reason/note fields allow at most 1,000 characters. Actions record a BookingEvent,
update the existing conversation, and emit relevant notifications after commit.
Expired holds cannot confirm; completion is only available on/after checkout.

`GET /rooms/{uuid}/calendar/?start=...&end=...` requires manager access.
Bulk calendar writes lock the same room as reservations and cannot reduce
inventory below active holds/reservations. Quantity reductions use the same guard.
