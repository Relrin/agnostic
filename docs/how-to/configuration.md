# Configuration and endpoints

Every external dependency is an **endpoint** you configure. Settings are read, highest priority first, from
environment variables, a `.env` file in the working directory, and an optional TOML file named by
`AGNOSTIC_CONFIG_FILE`. Kernel settings live in `backend/packages/agnostic-kernel/src/agnostic_kernel/settings.py`,
each module's in its own `settings.py`; the full list is in [reference/configuration](../reference/configuration.md).

Environment variables use the `AGNOSTIC_` prefix and `__` between levels:

```bash
AGNOSTIC_DATABASE__URL=postgresql://agnostic:secret@db.internal:5432/agnostic
AGNOSTIC_DATABASE__SSLMODE=verify-full
AGNOSTIC_DATABASE__TLS__CA_FILE=/etc/agnostic/ca.pem
AGNOSTIC_REDIS__URL=rediss://cache.internal:6380/0
AGNOSTIC_MODULES__DISABLED=assistant,sources
```

The same in TOML:

```toml
# AGNOSTIC_CONFIG_FILE=/etc/agnostic/agnostic.toml
[database]
url = "postgresql://agnostic:secret@db.internal:5432/agnostic"
sslmode = "verify-full"
tls = { ca_file = "/etc/agnostic/ca.pem" }

[modules]
disabled = ["assistant", "sources"]
```

Check what's in effect, and whether every endpoint answers:

```bash
uv run agnostic config check            # effective config, secrets redacted; enabled modules and job mode
uv run agnostic config check --connect  # + reachability, TLS, versions, extensions, cache commands, migrations
```

## Database: PostgreSQL or SQLite

| | PostgreSQL 17/18 | SQLite |
|---|---|---|
| Use for | production, integration tests, the dev stack | quick local runs, demos, unit tests |
| URL | `postgresql://user:pass@host:5432/db` | `sqlite:///agnostic.db` (or `sqlite:///:memory:`) |
| Extensions | `citext`, `pg_trgm` (created by migrations if allowed) | none |
| Background jobs | durable (Procrastinate), separate `agnostic worker` processes | in memory, inside the API process |
| Sessions, caches, rate limits | Redis | in the API process (`AGNOSTIC_CACHE__MODE=auto`) |
| TLS options | `sslmode`, `tls.ca_file`, `tls.cert_file`, `tls.key_file` | not applicable |

Switching is a URL change; models and migrations are the same code. Don't run production on SQLite: jobs don't
survive a restart and there is a single writer.

## Cache: Redis, Valkey or DragonflyDB

Redis 7.4+/8 is the reference; Valkey 8+ and DragonflyDB 1.x work too, because the control plane only uses commands
all three support. `config check --connect` names the detected engine and runs that command subset. Use `rediss://`
for TLS, or Sentinel:

```bash
AGNOSTIC_REDIS__SENTINELS=sentinel-1:26379,sentinel-2:26379
AGNOSTIC_REDIS__SENTINEL_MASTER=agnostic
```

Redis holds only ephemeral data. If it's down, `/readyz` reports it and live updates stop.

## Email

`AGNOSTIC_SMTP__URL` (`smtp://user:pass@host:587` with STARTTLS, or `smtps://host:465`) sends invitations and
password resets; `AGNOSTIC_SMTP__TIMEOUT` caps one send (10 s). Without it emails are written to the log, and admins
invite with *Create link only* and share the link themselves (`GET /api/v1/org` reports `email_delivery: false`).

## Tracing

Set `AGNOSTIC_OTEL__ENDPOINT` to an OTLP/HTTP traces URL (e.g. `http://collector:4318/v1/traces`) to export spans
for requests, SQL, Redis and outgoing HTTP. Headers (`AGNOSTIC_OTEL__HEADERS`, as JSON) and TLS options are
supported.

## Module settings

Each module reads its own namespace, e.g. `AGNOSTIC_GATEWAY__READ_SAMPLE_RATE=0.2`. Org-wide choices made in the app
(sign-in providers, AI features, audit retention, …) are stored in the database, not in settings.
