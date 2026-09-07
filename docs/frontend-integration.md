# Angular integration guide

Use `${API_ORIGIN}/api/v1`. Load `/config/` and `/reference/` during bootstrap.
Keep the short-lived access token in memory and send it as a Bearer token. Use the
rotating refresh token at `/auth/token/refresh/`, replace it after refresh, and POST
it to `/auth/logout/` on logout. A 401 triggers refresh/login; 403 means access is
denied.

Render structured `code` and field `errors`; include `request_id` in support cases.
Follow pagination links. Image fields are storage-backed URLs. Protect favourites,
conversations, viewing, booking, notifications, and verification routes. A typical
flow bootstraps config/reference, searches, loads detail, then authenticates before
favouriting, messaging, viewing, or booking. Swagger defines exact payloads.
