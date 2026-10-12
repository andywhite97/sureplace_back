# SurePlace Transactional Email Templates

SurePlace renders transactional email with Django templates before the delivery
provider sees the message. Bird remains a delivery provider only; templates are
not hosted in Bird.

## Structure

```text
notifications/templates/emails/
  base.html
  base.txt
  partials/
    header.html
    footer.html
    button.html
    details_card.html
    status_icon.html
    listing_card.html
  auth/
  bookings/
  viewings/
  verification/
  messaging/
  alerts/
```

Every HTML template has a matching plain-text template. Shared visual elements
live in partials so changes to the header, footer, CTA button, detail rows, and
listing cards are made once.

## Brand Rules

Use the locked SurePlace brand palette:

- Teal: `#0F9D83`
- Midnight: `#152B2A`
- Mist: `#F6F9F8`
- Slate: `#647471`
- Verification blue: `#2878D0`
- Amber: `#D99016`
- Error red: `#C73939`

Headings use `Manrope, Arial, Helvetica, sans-serif`; body copy uses
`Inter, Arial, Helvetica, sans-serif`. Email clients may ignore web fonts, so the
templates must not rely on remote font loading.

## Light and dark modes

Inline colours are the light-mode fallback. Teal text and CTA backgrounds use
`#087D69`, warning text uses `#99600B`, and information badges use `#2368B5`
to maintain readable contrast against their light surfaces.

`partials/theme.css`, included in the base template's style block, supplies a
dark palette through `prefers-color-scheme` and Outlook's `data-ogsc`/`data-ogsb`
wrapper selectors. Use the shared `sp-text`, `sp-muted`, `sp-accent`, `sp-card`,
`sp-surface`, `sp-border`, `sp-cta`, and `sp-status-*` classes whenever adding
coloured content. Pair background and foreground changes; leave listing photos
unchanged. Custom logo images have a white backing to protect dark lettering.

The rendering tests check normal text against its surfaces at a minimum 4.5:1
contrast ratio in both authored palettes. Email clients vary in their support
and some apply their own colour inversion, so check received previews in Apple
Mail, Gmail, and Outlook in both modes before release. See the
[email-client support table](https://www.caniemail.com/features/css-at-media-prefers-color-scheme/).

The footer uses:

```text
SurePlace
Property. Without the noise.
```

## Registry

`notifications.email_templates.TEMPLATES` maps template keys to:

- subject generator
- HTML template path
- text template path
- preheader
- default CTA label
- status treatment

Current keys:

- `auth.welcome`
- `auth.password_reset`
- `booking.requested_host`
- `booking.confirmed`
- `booking.declined`
- `booking.cancelled`
- `booking.expired`
- `viewing.requested`
- `viewing.confirmed`
- `viewing.declined`
- `verification.submitted`
- `verification.approved`
- `verification.rejected`
- `messaging.new_message`
- `alerts.saved_search_match`
- `transactional`

Use `template_for_notification()` to map existing `NotificationType` values to
template keys. Avoid duplicating template-key strings in domain code.

## Context Contract

`render_email(template_key, context)` returns rendered subject, HTML, text,
template key, and preheader. Shared context includes:

- `site_name`
- `brand_name`
- `tagline`
- `frontend_base_url`
- `logo_url`
- `support_email`
- `current_year`
- `preheader`
- `headline`
- `message`
- `cta_label`
- `cta_url`
- `secondary_cta_label`
- `secondary_cta_url`
- `details`
- `status`

Domain templates may also use:

- `booking`
- `property`
- `stay`
- `viewing`
- `verification`
- `sender`
- `listing`
- `matches`
- `saved_search`
- `message_preview`

Pass clean dictionaries rather than large ORM objects when possible.

## URLs

All CTA links are absolute URLs built from `FRONTEND_BASE_URL`. Do not hard-code
localhost or production domains in templates.

## Images

`EMAIL_LOGO_URL` may point to a public logo asset. If it is blank, the header
renders a text SurePlace wordmark.

Only public, safe-to-expose listing images should be used in template context.
Never include verification document URLs, private Cloudinary URLs, reset tokens in
metadata, or private contact details that the platform would not otherwise expose.

## Preview

Render a safe local preview:

```powershell
python manage.py preview_email booking.confirmed
```

This writes HTML to:

```text
tmp/email-previews/booking.confirmed.html
```

Print a text preview:

```powershell
python manage.py preview_email auth.password_reset --format text
```

The preview command uses sample data and does not contact Bird.

## Adding A Template

1. Add `emails/<domain>/<name>.html`.
2. Add the matching `emails/<domain>/<name>.txt`.
3. Register the key in `notifications.email_templates.TEMPLATES`.
4. Add a sample context in `sample_context()`.
5. Map any relevant `NotificationType` in `NOTIFICATION_TEMPLATE_KEYS`.
6. Add or update tests in `notifications/tests_email_templates.py`.

Keep templates transactional. Do not add newsletters, campaigns, bulk-send
features, promotional content, or marketing automation here.
