# SurePlace booking implementation report

Review date: 8 October 2026. Changes are local and uncommitted. The supplied
booking journey informed the guest and operator UX. The existing platform
architecture and the user's pre-existing frontend edits were preserved.

1. **Existing architecture.** Stay → RoomType → RoomAvailability provides nightly
   inventory. Booking already had guest/price snapshots, six lifecycle statuses,
   transaction services, room locks, per-guest idempotency, REST actions, Celery
   expiry, shared conversations and durable notifications. The audit is recorded
   in `booking-launch-audit.md`. One room type with multiple units remains the
   reservation model.

2. **Backend gaps.** Missing Stay booking mode and policy snapshots; no structured
   decline/cancellation reasons; no quoted-price conflict; unavailable rooms were
   hidden; pending expiry lacked notifications; calendar/bulk inventory and inactive
   agent access needed stronger guards. Guest checkout/detail and operator
   dashboard/detail/calendar flows were incomplete.

3. **Backend changes.** Added Stay booking mode and policies; Booking payment mode,
   policy snapshot and reasons; BookingEvent history; typed creation input and
   required consent/account email; quoted-price conflicts; unavailable-room
   explanations; guest/manager scoping and idempotency recovery; room-locked
   calendar/quantity updates; expiry and reminder notifications. Migrations:
   `stays/0006`, `bookings/0005`, `bookings/0006`, `notifications/0004`,
   `notifications/0005`. Run normal migrations before deployment.

4. **Lifecycle.** Reused PENDING, CONFIRMED, DECLINED, CANCELLED, COMPLETED, EXPIRED.
   Request mode creates a pending platform hold; instant mode creates confirmed
   inventory directly. Expired holds immediately stop consuming inventory and
   cannot confirm, even before Beat cleanup. Completion cannot precede checkout.
   Confirm/decline/cancel/complete serialize against new room reservations.

5. **Stay booking mode.** REQUEST_TO_BOOK is the migration default; INSTANT_BOOK
   is a Stay-level setting within the existing Stay form's policies step. Existing
   operators keep request mode until they enable instant booking. No room-level
   mode, selectable hold duration or payment processor was added.

6. **Guest components.** Stay detail now has date/guest selection, mobile date
   sheet, availability explanations, room unit controls and a booking summary.
   New `/stays/:slug/book` handles auth, guest details, review/consent and real
   success states. My Bookings separates pending, upcoming, past and cancelled.
   New `/account/bookings/:id` displays the reference, dates, guests, server price
   snapshot, policy, conversation, directions and cancellation dialog.

7. **Operator components.** `/account/manage/bookings` has real pending/arrival/
   departure/upcoming counts, recent reservations and searchable filters for
   status, date, Stay and room. Detail at `/account/manage/bookings/:id` provides
   guest details, requests, price/policies, confirm/decline/cancel/complete dialogs
   with reason validation, communication and calendar links. Arrivals/departures
   derive from confirmed bookings using Eswatini dates.

8. **Price and availability.** Angular displays the server's nightly quote and
   whole-stay total. Booking creation rechecks occupancy, minimum stay, blocked
   dates and available units inside the room lock. Custom rates and room quantities
   feed the snapshot. Changing guest counts invalidates quote and consent; 409
   price changes require explicit acknowledgement and renewed consent. Taxes and
   fees are shown only when nonzero; payment is at property.

9. **Auth handoff.** Login, registration and verification retain a safe local
   return URL to the exact checkout. Session intent whitelists Stay, room, dates,
   occupancy, idempotency key and resulting booking ID; it does not store guest
   contact details or special requests. Refresh restores the intent, revalidates
   availability and recovers an existing submission. Logout clears intent. SSR
   does not access browser storage. The details form prefills the authenticated
   profile and keeps account email read-only.

10. **Calendar.** Global `/account/manage/bookings/calendar` and existing per-Stay
    `/account/manage/stays/:id/calendar` use the same room calendar and booking
    APIs. Room/date cells show confirmed reservations, active pending holds,
    blocked/sold-out dates and booking previews. Checkout nights are exclusive.
    Calendar scrolling stays within the grid; bulk updates require one selected
    room and cannot undercut reserved inventory.

11. **Messaging.** Creation and transitions reuse the existing Stay conversation
    and create workflow messages there. Guest/operator links open that conversation.
    No parallel inbox or duplicate conversation architecture was introduced.

12. **Notifications.** Request submission, instant confirmation, operator decisions,
    cancellations, expiry and next-day arrival reminders use the existing service,
    preferences, email templates and worker. Guest cancellation also informs the
    operator. Event keys deduplicate notification and email scheduling. Routes
    target the correct guest/operator detail. The hourly reminder requires Beat
    and worker services; expiry retains its existing five-minute schedule.

13. **Privacy.** Booking APIs require authentication and verified email. Guest
    scope cannot expose managed customers; inactive agents cannot inspect or act
    on Stay bookings. Calendar access requires management capability. Public
    availability contains no guest details. Direct private IDs return denied/not
    found for unrelated users. Idempotency lookup always belongs to its guest.

14. **Responsive and live QA.** Isolated localhost data, an isolated SQLite DB and
    in-memory email prevented effects on real guests. Tested 360, 390, 430, 1024,
    1280, 1440 and 1600 pixel widths for checkout, operator dashboard, calendar and
    My Bookings: no page-level horizontal overflow. Verified mobile date sheet,
    room selection, auth return, guest prefill, consent-gated review, pending
    request, host confirmation, booking calendar preview/link, expiry cleanup,
    operator reasoned cancellation, instant confirmation, refresh recovery and
    guest cancellation. Unit tests cover decline/audit and error/retry behavior.
    Background operator polling runs outside Angular's zone so it does not keep
    hydration waiting for a recurring timer. Screenshots remain under the ignored
    `.booking-qa/screenshots` folder.

15. **Frontend tests.** Full Angular/Vitest regression suite: 80 files, 405 tests.
    Coverage includes stored intent/privacy/SSR, server quote display, checkout
    guest-count invalidation, consent, idempotent retry, price acknowledgement,
    success/auth gate, guest actions, operator metrics/filtering, calendar hold
    semantics, pagination and notification routing. Existing stale test fixtures
    were adjusted to current product behavior.

16. **Backend tests.** Full Django suite: 225 tests, OK with 2 skips. Covered
    input/contact/consent validation, account-email enforcement, inactive agents,
    foreign IDs, price conflicts, custom pricing, modes/snapshots, duplicate retries,
    transitions, reasons/events, expired holds including removed conversations, inventory release, private calendars,
    atomic bulk/quantity guards, notification routes and reminder deduplication.
    Tests use isolated SQLite, memory Celery transport/result storage and MD5 test
    hashing. Two PostgreSQL/PostGIS-specific tests were skipped: true row-lock
    concurrency and geometry behavior. Docker Desktop's engine was unavailable,
    so their deployment-database verification remains outstanding.

17. **Production validation.** Production Angular build passes within unchanged
    error budgets. Warnings remain for the initial bundle and several component
    styles, including the shared booking stylesheet's 4 KB warning budget; none
    exceed its 12 KB error budget. Dynamic listing prerender can fall back to
    client rendering when the configured API times out. Django standard checks
    pass and `makemigrations --check --dry-run --noinput` detects no missing schema
    changes. `DEBUG=false` / `check --deploy` cannot complete locally: production
    settings require Bird credentials and stop with `Set BIRD_API_KEY when
    EMAIL_PROVIDER=bird`. No fake credential or weakened startup guard was used.
    Before launch, run the production check and PostgreSQL/PostGIS tests in the
    configured deployment environment, apply migrations, then smoke-test worker/
    Beat, real email delivery and private booking deep links.
