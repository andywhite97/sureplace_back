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

The Angular app owns one authenticated background activity loop, initialized after
browser rendering. Unread counts and notification entries refresh every five
seconds while the page is visible, including public listing pages. Returning to
the tab or reconnecting refreshes immediately; logout cancels requests and clears
cached activity. Route teardown does not stop the app-wide loop. Open conversation
messages refresh every three seconds and the inbox every five seconds. New thread
messages preserve pending sends and update read state and global unread counts.
Opening a conversation starts its authorized mark-read request immediately, clears
that conversation's unread count optimistically and reconciles the global count
with the server. Failed requests restore the indicator and retry; older activity
responses cannot overwrite a newer local read action.
These are asynchronous HTTP updates using existing endpoints, without a WebSocket
or server-sent event deployment dependency.
