# Architecture

Angular consumes the versioned Django REST API. Django owns the accounts, agencies,
properties, stays, favourites, alerts, messaging, bookings, notifications,
verification, and moderation domains. PostgreSQL/PostGIS is the system of record;
Cloudinary stores media. Redis carries Celery jobs, a worker executes them, and
Celery Beat is the single scheduler. WhiteNoise serves static assets, an external
provider sends email, and Render deploys the services.

Money calculations use `Decimal`, booking dates remain dates, and timezone-aware
business scheduling uses `Africa/Mbabane`.
