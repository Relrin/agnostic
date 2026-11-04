# API conventions

- Base path `/api/v1`. Org-wide resources sit directly under it; instance-scoped resources under
  `/api/v1/instances/{instance}/…`. Health endpoints are `/healthz` and `/readyz`; git-host webhooks `/hooks/*`; SCIM
  `/scim/v2`.
- JSON with `snake_case` fields; timestamps are RFC 3339 in UTC.
- The OpenAPI document (`/api/v1/openapi.json`) is the contract; the frontend client and the
  [API reference](api.md) are generated from it.
- Code: `backend/packages/agnostic-kernel/src/agnostic_kernel/` (`errors.py`, `http.py`, `ids.py`, `pagination.py`).

## Errors: `application/problem+json`

Every error is an RFC 9457 problem with a stable `code`:

| Field | Meaning |
|---|---|
| `type` | `urn:agnostic:problem:<code>` |
| `title` | short human summary |
| `status` | HTTP status |
| `code` | stable machine code; switch on this |
| `detail` | what happened, in a sentence (when there is something specific to say) |
| `instance` | request path |
| `request_id` | same as the `X-Request-Id` response header |
| `errors` | field errors for `validation_failed`: `[{loc, msg, type}]` |

Kernel codes: `not_found`, `validation_failed`, `conflict`, `version_conflict`, `unauthenticated`, `scope_missing`,
`forbidden`, `rate_limited`, `unavailable`, `internal`; from HTTP statuses: `bad_request`, `method_not_allowed`,
`unsupported_media_type`; `database_unavailable` (503 with `Retry-After`) when the database is down or not answering.
Modules add their own (`instance_unreachable`, `capability_disabled`, `sso_required`, …) by subclassing `AppError`.

## Request ids

Send `X-Request-Id` (1–128 characters of `A-Z a-z 0-9 . _ : -`) to correlate; otherwise the API generates
`req_<ULID>`. It is echoed in the response header, the problem body and every log line.

## Ids

Control-plane ids are prefixed ULIDs: `<prefix>_<26-char ULID>`, e.g. `usr_01M6A0EEZEQ373S26F20142FZ5`. They sort by
creation time. Prefixes are 2–5 lowercase letters per entity (`usr`, `ins`, `inv`, `grp`, `rol`, `bnd`, `sac`, `evt`,
`src`, `ds`, …). AgentOS ids are shown as AgentOS returns them, never re-prefixed.

## Pagination

Lists take `?limit=` (1–200, default 50) and `?cursor=` and return:

```json
{"data": [...], "next_cursor": "eyJhZnRlciI6…", "total_estimate": null}
```

`next_cursor` is opaque; pass it back unchanged. `null` means there are no more items.
