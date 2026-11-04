# Backend kernel

`agnostic-kernel` (`backend/packages/agnostic-kernel/src/agnostic_kernel/`) holds what modules share and nothing
product-specific. It never imports a module (import-linter contract).

| File | Provides |
|---|---|
| `settings.py`, `tls.py` | `Settings`: `AGNOSTIC_*` env vars (`__` nesting), `.env`, optional TOML (`AGNOSTIC_CONFIG_FILE`); endpoint sections with TLS options; `module_settings_config()` |
| `db.py`, `tables.py` | async SQLAlchemy engine (asyncpg or aiosqlite), `make_metadata()`, `JsonDocument`, psycopg conninfo; kernel tables |
| `migrations/`, `migrations_runner.py` | one Alembic environment, base `k0001_kernel_base`, one branch per module ([migrations](../how-to/migrations.md)) |
| `modules.py`, `container.py` | the `Module` protocol, `BaseModule`, discovery and ordering; the dishka container |
| `auth.py`, `bootstrap.py` | `Principal`, `PrincipalResolver`, `Authorizer`, `Bootstrapper` ports (provided by identity, access, org) |
| `errors.py`, `http.py`, `context.py`, `security_headers.py` | RFC 9457 problems and `AppError`; request-id middleware and request context; CSP (Trusted Types), HSTS |
| `cache.py`, `ephemeral.py` | Redis client (URL or Sentinel; Valkey and DragonflyDB work) and its command-subset probe; `EphemeralStore` with `MemoryStore` and `DegradingStore` |
| `events.py`, `domain_events.py` | realtime `EventBus` (Redis pub/sub + replay stream, `MemoryEventBus`); `DomainEvents` and the `kernel.domain_event` job |
| `jobs.py`, `job_admin.py` | Procrastinate app, `JobSpec` registration, `job_container()`, `JobQueue`, `JobProgressReporter`; queue depth, lag, failed jobs, retry |
| `crypto.py`, `keys/`, `rewrap.py` | `SecretBox` envelope encryption (AES-256-GCM data keys wrapped by the master key); key providers (local, Vault, AWS KMS, GCP KMS, Azure Key Vault); `agnostic secrets rotate` |
| `mail.py`, `aws_sigv4.py` | SMTP (logs the mail when none is configured); SigV4 for S3 and KMS |
| `tools.py` | `ToolSpec`: read-only assistant tools modules contribute |
| `diagnostics.py`, `checks.py`, `health.py` | `CheckResult` / `StatusItem`; endpoint probes; `/healthz`, `/readyz` |
| `logging.py`, `telemetry.py`, `metrics.py` | structlog with secret redaction; OpenTelemetry over OTLP/HTTP; Prometheus metrics on their own port |
| `ids.py`, `pagination.py`, `testing.py` | prefixed ULIDs (`usr_…`); `Page[T]` with opaque cursors; test helpers |

## Request path

Middleware, outermost first: metrics, security headers, request id, CORS (when configured), the web app (when
`AGNOSTIC_HTTP__WEB_DIR` is set). Routes resolve the `Principal` through identity, which checks the session cookie
and `X-CSRF-Token` on unsafe requests. Each request gets a request-scoped dishka container with one `AsyncSession`,
committed by the use case.

![Request path: middleware, router, use case, authorizer, domain, repository, commit and audit, response or problem+json](images/request-path.svg)

## Dependency injection

The composition root (`agnostic_server.app.create_app`, or the worker) builds the container from `KernelProvider`
(settings, loaded modules, engine, sessions, Redis, the ephemeral store, the event bus, `SecretBox`, the mailer,
the Procrastinate app, `JobQueue`, `JobProgressReporter`),
each enabled module's settings model, and each module's `provide()`. Routes use `DishkaRoute` with `FromDishka[T]`;
jobs use `job_container(context)`.

## Database

- Every table lives in schema `agnostic` with its module's prefix (`access_roles`, `inst_instances`, `apr_routes`);
  constraint names are deterministic.
- PostgreSQL in production; SQLite for development and tests, where `schema_translate_map` drops the schema so models
  and migrations are the same code.
- Use `JsonDocument` for JSON (jsonb on PostgreSQL) and `func.now()` for timestamps.

## Errors

Use cases raise `AppError` subclasses (`NotFoundError`, `ValidationFailedError`, `ConflictError`,
`VersionConflictError`, `UnauthenticatedError`, `ScopeMissingError`, `ForbiddenError`, `RateLimitedError`, `ServiceUnavailableError`). Handlers turn
them, HTTP and validation errors, and unhandled exceptions into `application/problem+json`:

```json
{"type": "urn:agnostic:problem:not_found", "title": "Not found", "status": 404, "code": "not_found",
 "detail": "There is no instance 'prod-agentos'.", "instance": "/api/v1/instances/prod-agentos",
 "request_id": "req_…"}
```

`code` is stable; clients switch on it. See [API conventions](../reference/api-conventions.md).

## Health

- `/healthz`: the process is alive.
- `/readyz`: database, cache and migrations. `503` only when the database is down or migrations aren't at head
  (including "unknown revision in the database" for revisions this version doesn't ship); a cache outage reports
  `degraded` so replicas stay in rotation.

## Python 3.15

- Route modules using `DishkaRoute` don't use `from __future__ import annotations`: FastAPI must resolve the wrapped
  endpoints' annotations against the module.
- On Windows every entry point runs a selector event loop (`agnostic_server.loops`): psycopg's async driver can't use
  the Proactor loop.
