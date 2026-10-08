# Booking launch audit

The existing architecture is retained: Stay → RoomType → RoomAvailability,
Booking with nightly/guest snapshots, room-row transaction locks, guest-scoped
idempotency keys, six existing statuses, action endpoints, Celery hold expiry,
booking-aware room calendars, reusable conversations and durable notifications.
The preceding launch fixes already validate inputs, restrict inactive agents,
prevent early completion and expired confirmations, and serialize confirmations.

Gaps against the approved flow: no stay-level request/instant setting, no policy
snapshot, no structured decline/cancellation reason, no quoted-price conflict,
no guest checkout/detail route or typed persisted intent, no owner dashboard,
filtering/detail workspace or booking blocks on the calendar. Availability hides
unavailable rooms and does not explain minimum-stay/occupancy failures. Expiry
does not emit lifecycle notifications. These are extensions of existing services.

Launch scope: one room type per reservation, with multiple units. No mixed-room
cart, online payments, invented fees, room-level modes or new operational statuses.
Pay at property is snapshotted. Dates, room selection and an idempotency token
may survive browser refresh; guest contact details and requests are not persisted.
