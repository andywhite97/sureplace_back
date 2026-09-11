# SurePlace Email Delivery

SurePlace keeps email-producing business logic in domain services, renders
HTML/plain-text content with Django templates, and delivers mail through a small
provider boundary:

```text
Domain service -> notifications.services -> Django templates -> Celery task -> EmailProvider -> provider API
```

Development and tests can continue to use Django email backends. Production uses
Bird's HTTP Email API by setting `EMAIL_PROVIDER=bird`.

Template structure, registry keys, context rules, and preview tooling are covered
in `docs/email-templates.md`.

## Providers

`EMAIL_PROVIDER=django` sends through Django's configured `EMAIL_BACKEND`. This is
the default for local development and is safe with console or locmem backends.

`EMAIL_PROVIDER=bird` sends through `BirdEmailProvider` using:

```text
POST https://<region>.platform.bird.com/v1/email/messages
Authorization: Bearer <BIRD_API_KEY>
Content-Type: application/json
```

The Bird base URL is derived from the key prefix when possible:

- `bk_us1_...` -> `https://us1.platform.bird.com`
- `bk_eu1_...` -> `https://eu1.platform.bird.com`

`BIRD_API_BASE_URL` may override this, but only to a supported HTTPS Bird regional
host. In production, insecure or arbitrary hosts are rejected at startup.

## Environment

Required for local development:

```text
EMAIL_PROVIDER=django
EMAIL_DELIVERY_MODE=async
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=SurePlace <noreply@sureplace.co.sz>
DEFAULT_FROM_NAME=SurePlace
FRONTEND_BASE_URL=http://localhost:4200
```

Required for production:

```text
EMAIL_PROVIDER=bird
EMAIL_DELIVERY_MODE=async
BIRD_API_KEY=<server-side Bird API key>
DEFAULT_FROM_EMAIL=SurePlace <noreply@verified-domain>
DEFAULT_FROM_NAME=SurePlace
FRONTEND_BASE_URL=<Angular HTTPS origin>
```

Optional:

```text
BIRD_API_BASE_URL=
BIRD_REQUEST_TIMEOUT_SECONDS=10
DEFAULT_REPLY_TO_EMAIL=
EMAIL_LOGO_URL=
EMAIL_VERIFICATION_TTL_SECONDS=86400
BIRD_TRACK_OPENS=false
BIRD_TRACK_CLICKS=false
```

Bird credentials are server-side only. They must never be exposed to Angular,
committed to git, or written to logs.

## Delivery Mode

`EMAIL_DELIVERY_MODE` controls whether transactional email is handed to Celery or
sent immediately through the same SurePlace provider abstraction:

- `async` (default): create `EmailDelivery`, enqueue the Celery delivery task, and
  let the worker call the configured provider. This remains the intended
  production mode.
- `sync`: create `EmailDelivery` and call the configured provider immediately in
  the current process. This is intended only for staging/live testing, for
  example on Render while confirming Bird credentials and sender-domain setup.

For Render live testing:

```text
EMAIL_DELIVERY_MODE=sync
```

Sync mode does not call Bird from views. Views and domain services still use the
normal SurePlace email service, which renders templates, stores `EmailDelivery`,
uses the configured provider, captures provider message IDs, and preserves the
same permanent/transient Bird error handling.

## Sender Domain

Production `DEFAULT_FROM_EMAIL` must use a Bird-verified sending domain, for
example `SurePlace <noreply@sureplace.co.sz>` once that domain is verified. If a
support mailbox exists, set `DEFAULT_REPLY_TO_EMAIL`; otherwise reply-to is
omitted.

Manual Bird setup before production:

1. Create the Bird account/workspace.
2. Create a narrowly scoped API key for email sending if Bird's UI supports it.
3. Verify the SurePlace sending domain.
4. Add the DNS records shown by Bird.
5. Choose the verified sender address.
6. Store the API key in Render environment variables for both web and worker.
7. Perform a sandbox/test send.
8. Perform a production-domain test send after DNS verification.

## Payload

SurePlace sends inline rendered transactional mail. The provider payload includes
`from`, `to`, optional `cc`, optional `bcc`, `subject`, `html`, `text`, and:

```json
{"category": "transactional"}
```

Transactional classification is always included for Bird sends. Open and click
tracking default to disabled unless explicitly enabled with environment variables.
Only non-sensitive metadata such as `notification_id` and `email_delivery_id` is
sent.

## Delivery Records

`EmailDelivery` records store support/debug fields without storing the rendered
body:

- recipient
- subject
- notification link when available
- provider
- provider message ID
- template key
- status
- attempts
- safe error code/message
- accepted/delivered/failed timestamps

Bird HTTP `202` means the message was accepted for asynchronous processing. It is
stored as `accepted`, not `delivered`. Future Bird webhook work can update records
to delivered, bounced, rejected, or failed.

## Celery And Retries

Normal notification emails are queued after the database transaction commits.
Celery calls the provider and retries transient failures:

- timeout
- connection error
- Bird `429`
- Bird `5xx`

Retries are bounded with exponential backoff, jitter, and a cap. Permanent Bird
validation failures such as `422` are recorded and are not retried indefinitely.
There is no automatic production fallback from Bird to Django SMTP because that
can duplicate uncertain deliveries.

Password reset uses the same provider abstraction and still keeps Django's reset
token generation and account-enumeration-safe response.

## Email Verification

Registration creates users with `is_email_verified=false` and queues only the
`auth.verify_email` transactional email after the database transaction commits.
Welcome email (`auth.welcome`) is sent once, after the first successful email
verification transition.

Verification links use `FRONTEND_BASE_URL` and the public Angular route:

```text
/verify-email?token=<signed-token>
```

The signed token is purpose-specific, contains only user ID, email, and purpose,
and expires after `EMAIL_VERIFICATION_TTL_SECONDS` (default 24 hours). Tokens are
naturally invalidated by email changes because the signed email must still match
the current user email.

API endpoints:

- `POST /api/v1/auth/verify-email/` with `{ "token": "..." }`
- `POST /api/v1/auth/resend-verification/` with `{ "email": "user@example.com" }`

The resend endpoint always returns a generic response and does not reveal whether
an account exists, is verified, or is disabled. Verification and resend use the
`email_verification` DRF throttle scope.

Sensitive authenticated write actions return `403` with code
`email_not_verified` until the user verifies email. Public browsing, login,
password reset, verification, and resend remain available.

## Email Provider Diagnostics

Use the CLI-only diagnostic command to verify the configured transactional email
provider from the same Django environment as the backend:

```bash
python manage.py test_email_provider you@example.com
```

Direct mode renders the `system.email_diagnostic` transactional template, creates
an `EmailDelivery`, and calls the configured provider synchronously through the
normal SurePlace provider abstraction. With `EMAIL_PROVIDER=bird`, a successful
Bird HTTP `202` is reported as `accepted`, not delivered:

```text
Email provider diagnostic successful.
Provider: bird
Status: accepted
Message ID: em_...
Bird accepted the message for delivery.
```

Use Bird dashboard events or provider logs to inspect later delivery, bounce, or
rejection status.

To validate configuration and rendering without sending or queueing anything:

```bash
python manage.py test_email_provider you@example.com --dry-run
```

To verify that the normal asynchronous path can queue a diagnostic email:

```bash
python manage.py test_email_provider you@example.com --via-celery
```

`--via-celery` queues the rendered email through the existing Celery delivery
task and prints the local delivery ID. It does not print a Bird message ID because
Bird has not accepted the message until the worker executes the task.

The command validates the recipient and configured sender before attempting
delivery. It prints only safe operational details such as provider, Django backend
for `EMAIL_PROVIDER=django`, sender, recipient, status, and provider message ID.
It never prints API keys, authorization headers, database URLs, or raw provider
responses.

Common Bird failures are mapped to operator messages:

- `401`: check `BIRD_API_KEY`.
- `403`: check API key permissions or scope.
- `422`: check the payload, sender, and that `DEFAULT_FROM_EMAIL` belongs to a
  verified Bird sending domain.
- `429`: rate limit reached; retry later.
- `5xx` or timeout: Bird is temporarily unavailable.

From the Render backend shell, run the same command so it picks up the deployed
service environment variables:

```bash
python manage.py test_email_provider your-real-test-address@example.com
```

For the Celery mode on Render, confirm the worker service is running first.

## Covered Email Types

The centralized notification path covers booking, viewing, verification,
saved-search, listing reminder, moderation/listing status, system, and important
message notification mail. Password reset is routed separately through the same
delivery provider.

## Testing

Unit tests mock the Bird network boundary and never send real Bird requests.
Django backend tests use the locmem backend. Health checks must not call Bird; use
deployment smoke tests for provider verification.
