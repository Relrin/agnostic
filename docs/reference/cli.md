# CLI reference

`agnostic` is installed with the backend (`cd backend && uv run agnostic …`). Every command reads the same
settings as the server ([configuration](configuration.md)).

| Command | Does |
|---|---|
| `agnostic api [--host H] [--port P] [--reload]` | serve the HTTP API (uvicorn; one worker per container) |
| `agnostic worker [-q QUEUE]… [--concurrency N]` | run background jobs and periodic schedules; PostgreSQL only |
| `agnostic dev` | API with reload + worker restarted on code changes (SQLite: API only, jobs embedded) |
| `agnostic db upgrade [REVISION]` | apply migrations of the kernel and every installed module (default `heads`) |
| `agnostic db downgrade REVISION` | revert to a revision, e.g. `hello@base` or `base` |
| `agnostic db current` | applied revisions, heads and pending revisions |
| `agnostic config check [--connect]` | effective configuration with secrets redacted; `--connect` probes every endpoint and exits 1 on a failure |
| `agnostic modules list` | installed modules: version, enabled/disabled, dependencies, routes, jobs |
| `agnostic openapi [--out FILE]` | write the OpenAPI document (stdout by default) |

Later phases add `agnostic bootstrap`, `agnostic instances …`, `agnostic export|import` and
`agnostic audit restore`.

Exit codes: `0` success, `1` a check or graph error, `2` a usage error (including `worker` on SQLite).

`python -m agnostic_server` is equivalent to `agnostic`.
