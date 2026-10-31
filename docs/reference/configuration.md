# Configuration reference

Environment variables use the `AGNOSTIC_` prefix and `__` between levels. Lists accept comma-separated values.
TOML files (`AGNOSTIC_CONFIG_FILE`) use the same names as sections and keys. Source of truth:
`backend/packages/agnostic-kernel/src/agnostic_kernel/settings.py`.

## General

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_ENV` | `production` | `development`, `test` or `production` |
| `AGNOSTIC_CONFIG_FILE` | — | path to a TOML settings file (lower priority than env vars) |

## Database

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_DATABASE__URL` | `postgresql://agnostic:agnostic@localhost:5432/agnostic` | `postgresql://…` or `sqlite:///path.db` |
| `AGNOSTIC_DATABASE__SSLMODE` | `prefer` | libpq mode: `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full` |
| `AGNOSTIC_DATABASE__TLS__CA_FILE` | — | CA bundle to verify the server |
| `AGNOSTIC_DATABASE__TLS__CERT_FILE` / `__KEY_FILE` | — | client certificate and key |
| `AGNOSTIC_DATABASE__POOL_SIZE` | `10` | connections per process |
| `AGNOSTIC_DATABASE__MAX_OVERFLOW` | `10` | extra connections under load |
| `AGNOSTIC_DATABASE__CONNECT_TIMEOUT` | `5` | seconds |
| `AGNOSTIC_DATABASE__ECHO` | `false` | log SQL |

## Cache

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_REDIS__URL` | `redis://localhost:6379/0` | `redis://` or `rediss://` (TLS) |
| `AGNOSTIC_REDIS__SENTINELS` | — | `host:port,host:port`; use with `SENTINEL_MASTER` |
| `AGNOSTIC_REDIS__SENTINEL_MASTER` | — | Sentinel service name |
| `AGNOSTIC_REDIS__TLS__CA_FILE` / `__CERT_FILE` / `__KEY_FILE` | — | TLS material |
| `AGNOSTIC_REDIS__SOCKET_TIMEOUT` | `5` | seconds |

## Jobs

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_JOBS__MODE` | `auto` | `worker` (separate processes), `embedded` (inside the API), `auto` (worker on PostgreSQL, embedded on SQLite) |
| `AGNOSTIC_JOBS__CONCURRENCY` | `10` | jobs run in parallel per worker |
| `AGNOSTIC_JOBS__QUEUES` | all | queues a worker listens to |

## HTTP

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_HTTP__HOST` | `127.0.0.1` | bind address for `agnostic api` |
| `AGNOSTIC_HTTP__PORT` | `8000` | port |
| `AGNOSTIC_HTTP__CORS_ORIGINS` | — | allowed origins (not needed same-origin) |

## Logging and tracing

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_LOG__LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `AGNOSTIC_LOG__FORMAT` | `json` | `json` or `console` |
| `AGNOSTIC_OTEL__ENDPOINT` | — | OTLP/HTTP traces URL; tracing is off without it |
| `AGNOSTIC_OTEL__HEADERS` | — | JSON object of headers, e.g. `{"authorization": "Bearer …"}` |
| `AGNOSTIC_OTEL__SERVICE_NAME` | `agnostic` | `service.name` resource attribute |
| `AGNOSTIC_OTEL__TLS__CA_FILE` / `__CERT_FILE` / `__KEY_FILE` | — | TLS material |

## Modules

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_MODULES__DISABLED` | — | modules to turn off, e.g. `assistant,sources` |
| `AGNOSTIC_HELLO__REPLY_PREFIX` | `Hello` | sample module: reply greeting |
| `AGNOSTIC_HELLO__HEARTBEAT_CRON` | `*/5 * * * *` | sample module: periodic job schedule |

## Tests only

| Variable | Meaning |
|---|---|
| `AGNOSTIC_TEST_DATABASE_URL`, `AGNOSTIC_TEST_REDIS_URL` | use existing servers instead of testcontainers |
| `AGNOSTIC_TEST_REDIS_IMAGE` | cache image for testcontainers (Valkey/Dragonfly compatibility) |
| `AGNOSTIC_CONTRACT_RUNTIME_URL` | runtime for contract tests |
