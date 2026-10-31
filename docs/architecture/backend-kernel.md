# Backend kernel

`agnostic-kernel` (`backend/packages/agnostic-kernel/src/agnostic_kernel/`) holds everything modules share and
nothing product-specific. Modules depend on it; it never imports a module (an import-linter contract enforces this).

| Module | Provides |
|---|---|
| `settings.py` | `Settings` (pydantic-settings): `AGNOSTIC_*` env vars with `__` nesting, `.env`, optional TOML file; endpoint sections with TLS options; `module_settings_config()` for module settings |
| `tls.py` | TLS contexts and libpq parameters from endpoint `TlsOptions` |
| `logging.py` | structlog JSON/console logs, stdlib bridge, secret redaction |
| `telemetry.py` | OpenTelemetry tracing over OTLP/HTTP when `AGNOSTIC_OTEL__ENDPOINT` is set |
| `db.py` | async SQLAlchemy engine (asyncpg, or aiosqlite for SQLite), `make_metadata()`, `JsonDocument`, psycopg conninfo |
| `migrations/`, `migrations_runner.py` | one Alembic environment, a branch per module, `upgrade`/`downgrade`/`state` |
| `cache.py` | Redis client (URL or Sentinel), server detection, command-subset probe |
| `jobs.py` | Procrastinate app, job registration, `job_container()`, `JobQueue`, `JobProgressReporter` |
| `modules.py` | the `Module` protocol, `BaseModule`, descriptors, discovery and dependency ordering |
| `container.py` | dishka container: kernel services + module providers |
| `errors.py` | RFC 9457 problem responses and the `AppError` hierarchy |
| `ids.py` | prefixed ULIDs |
| `pagination.py` | `Page[T]` envelope and opaque cursors |
| `http.py`, `context.py` | request-id middleware and context |
| `health.py`, `checks.py` | `/healthz`, `/readyz`, and the endpoint probes behind `config check --connect` |
| `testing.py` | settings and polling helpers for tests |

## Request flow

```
HTTP → RequestIdMiddleware → (OTel) → router (Pydantic validation) → use case → domain → repository
     → response model → JSON          errors anywhere → problem+json with the request id
```

Each request gets a request-scoped dishka container: one `AsyncSession` per request, committed by the use case.

## Dependency injection

The container is built by the composition root (`agnostic_server.app.create_app` or the worker) from:

- `KernelProvider`: `Settings`, `LoadedModules`, `AsyncEngine`, `async_sessionmaker`, `AsyncSession` (request
  scope), `Redis`, the Procrastinate `App` (opened for the app's lifetime), `JobQueue`, `JobProgressReporter`;
- each enabled module's settings model (`AGNOSTIC_<MODULE>__*`);
- each enabled module's own providers (`Module.provide()`).

Routes use `DishkaRoute` and `FromDishka[T]` parameters. Jobs use `job_container(context)`.

## Database

- Every table lives in schema `agnostic`, named `<module>_<thing>`; constraint names are deterministic.
- PostgreSQL is the production backend; SQLite is supported for development and tests. On SQLite the engine maps
  the `agnostic` schema away with `schema_translate_map`, so models and migrations are the same code.
- Use `JsonDocument` for JSON columns (jsonb on PostgreSQL) and `func.now()` for timestamps; both work on both
  backends.

## Errors

Raise an `AppError` subclass from use cases (`NotFoundError`, `ValidationFailedError`, `ConflictError`,
`VersionConflictError`, `UnauthenticatedError`, `ScopeMissingError`, `ServiceUnavailableError`). Handlers turn
them, HTTP errors, validation errors and unhandled exceptions into `application/problem+json`:

```json
{"type": "urn:agnostic:problem:not_found", "title": "Not found", "status": 404, "code": "not_found",
 "detail": "Greeting hel_… doesn't exist.", "instance": "/api/v1/hello/greetings/hel_…", "request_id": "req_…"}
```

`code` is stable; clients switch on it. See [API conventions](../reference/api-conventions.md).

## Health

- `/healthz`: process is alive.
- `/readyz`: database reachable, cache reachable, migrations at head; `503` with per-check details otherwise.

## Python 3.15

The control plane targets Python 3.15. Two consequences in code:

- Route modules that use `DishkaRoute` don't use `from __future__ import annotations`: dishka wraps endpoints and
  FastAPI must resolve their annotations against the module (3.15 evaluates annotations lazily anyway).
- Every entry point runs on a selector event loop on Windows (`agnostic_server.loops`), because psycopg's async
  driver can't use the Proactor loop.
