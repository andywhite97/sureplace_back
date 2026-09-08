# SurePlace Email Delivery

SurePlace keeps email-producing business logic in domain services and delivers
mail through a small provider boundary:

```text
Domain service -> notifications.services -> Celery task -> EmailProvider -> provider API
```

Development and tests can continue to use Django email backends. Production uses
Bird's HTTP Email API by setting `EMAIL_PROVIDER=bird`.

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
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=SurePlace <noreply@sureplace.co.sz>
DEFAULT_FROM_NAME=SurePlace
FRONTEND_BASE_URL=http://localhost:4200
```

Required for production:

```text
EMAIL_PROVIDER=bird
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
BIRD_TRACK_OPENS=false
BIRD_TRACK_CLICKS=false
```

Bird credentials are server-side only. They must never be exposed to Angular,
committed to git, or written to logs.

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

## Covered Email Types

The centralized notification path covers booking, viewing, verification,
saved-search, listing reminder, moderation/listing status, system, and important
message notification mail. Password reset is routed separately through the same
delivery provider.

## Testing

Unit tests mock the Bird network boundary and never send real Bird requests.
Django backend tests use the locmem backend. Health checks must not call Bird; use
deployment smoke tests for provider verification.
