# Property availability

Creators confirm availability during submission and can use **Still available**,
**Mark available**, or **Mark unavailable** on Manage Properties. Editing a published
listing also provides the availability checkbox on the review step.

Each confirmation restarts the timer. After 14 days, the daily availability task
sends one in-app/email reminder to the owner and assigned active agent, honoring
notification preferences. After 21 days without confirmation, it marks the property
unavailable and notifies them. Confirmation restores availability without changing
the publication/moderation status. Unavailable properties are excluded from public
search, featured results, agent/agency listing previews, and the sitemap.

Before deploying, run `python manage.py migrate`. Configure
`PROPERTY_AVAILABILITY_REMINDER_DAYS=14` and `PROPERTY_AVAILABILITY_STALE_DAYS=21`.
Both a Celery worker and Celery Beat must run (see `render-deployment.md`); the
existing `availability-reminders` beat entry checks daily, so a notification/status
change occurs on the first scheduled run after its threshold. This uses the
application scheduler, not a Codex chat automation.

For legacy available properties without a confirmation timestamp, the clock starts
at their publication date (or creation date if none exists). Listings already older
than 21 days become unavailable on the next check.
