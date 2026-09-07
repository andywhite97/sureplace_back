# API contract

`/api/v1/` is canonical; `/api/` temporarily aliases the same views. OpenAPI is at
`/api/v1/schema/`, Swagger at `/api/v1/docs/`, and ReDoc at `/api/v1/redoc/`.
JWT endpoints live under `auth/`; refresh tokens rotate and logout revokes them.
Collections use `count`, `next`, `previous`, and `results`; `page_size` defaults to
20 and is capped at 100.

Errors contain `code`, `message`, field-level `errors`, and `request_id`. Responses
return `X-Request-ID`. Public bootstrap data is at `config/` and `reference/`. UUID
resources return 403 or 404 according to whether existence can safely be revealed.
