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
| `AGNOSTIC_CACHE__MODE` | `auto` | where sessions, scope caches and rate limits live: `redis`, `memory` (one process: SQLite installs and tests), `auto` (redis on PostgreSQL, memory on SQLite) |

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
| `AGNOSTIC_HTTP__PUBLIC_URL` | `http://{host}:{port}` | the URL people open (behind the proxy): email links, SSO callback URLs, the JWT issuer |
| `AGNOSTIC_HTTP__SECURE_COOKIES` | on unless `PUBLIC_URL` is `http://` | mark the session and CSRF cookies `Secure` |

## Secrets and email

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_SECRETS__MASTER_KEY` | — | base64 of 32 random bytes: the key-encryption key for secrets at rest (instance private keys, security keys). Required in production; development uses a fixed insecure key with a warning |
| `AGNOSTIC_SECRETS__MASTER_KEY_FILE` | — | read the master key from a file instead |
| `AGNOSTIC_SMTP__URL` | — | `smtp://user:pass@host:587` (STARTTLS when offered) or `smtps://host:465`; without it, emails (invitations, password resets) are written to the log |
| `AGNOSTIC_SMTP__SENDER` | `Agnostic <agnostic@localhost>` | `From:` address |
| `AGNOSTIC_SMTP__TLS__CA_FILE` / `__CERT_FILE` / `__KEY_FILE` | — | TLS material |

## Sign-in (identity module)

See [sign-in providers](../how-to/sign-in-providers.md) for setup per identity provider.

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_IDENTITY__LOCAL_LOGIN` | `true` | email + password accounts; turn off to require SSO |
| `AGNOSTIC_IDENTITY__PROVIDERS__<ID>__PRESET` | `oidc` | `github`, `gitlab`, `google`, `okta` or `oidc` (any OIDC IdP) |
| `…__<ID>__CLIENT_ID` / `__CLIENT_SECRET` | — | OAuth client registered at the provider; callback URL `{PUBLIC_URL}/api/v1/auth/sso/<id>/callback` |
| `…__<ID>__ISSUER` | preset default | OIDC issuer (required for Okta and generic OIDC; self-managed GitLab) |
| `…__<ID>__BASE_URL` | `https://github.com` | GitHub Enterprise Server URL |
| `…__<ID>__DISPLAY_NAME` / `__SCOPES` | preset default | button label; requested scopes |
| `…__<ID>__JIT_PROVISIONING` | `false` | people without an invitation join as Members on first sign-in… |
| `…__<ID>__ALLOWED_EMAIL_DOMAINS` | — | …when their email domain is listed (Google: also preselects the Workspace domain) |
| `…__<ID>__TRUST_UNVERIFIED_EMAIL` | `false` | accept emails the provider hasn't verified |
| `…__<ID>__ENABLED` | `true` | hide a provider without deleting its settings |
| `AGNOSTIC_IDENTITY__PASSWORD_MIN_LENGTH` | `12` | |
| `AGNOSTIC_IDENTITY__SESSION_IDLE_HOURS` / `__SESSION_ABSOLUTE_DAYS` | `12` / `7` | sliding and absolute session lifetime |
| `AGNOSTIC_IDENTITY__LOCKOUT_THRESHOLD` / `__LOCKOUT_MINUTES` | `5` / `15` | failed sign-ins before an account is locked, and for how long |
| `AGNOSTIC_IDENTITY__LOGIN_ATTEMPTS_PER_IP_PER_MINUTE` | `30` | |
| `AGNOSTIC_IDENTITY__PASSWORD_RESET_MINUTES` | `60` | reset link lifetime |

## Instances and gateway

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_INSTANCES__ISSUER` | `PUBLIC_URL` | `iss` of the JWTs minted for runtimes |
| `AGNOSTIC_INSTANCES__TOKEN_TTL_SECONDS` | `300` | lifetime of minted JWTs |
| `AGNOSTIC_INSTANCES__HEALTH_CRON` / `__SNAPSHOT_CRON` | `* * * * *` / `*/5 * * * *` | health polling and `/config` + capability refresh |
| `AGNOSTIC_GATEWAY__READ_SAMPLE_RATE` | `0.05` | share of allowed reads written to the audit log (writes and denials always are) |
| `AGNOSTIC_GATEWAY__RATE_READ_PER_MINUTE` / `__RATE_WRITE_…` / `__RATE_RUN_…` | `1200` / `240` / `120` | per person and instance; `0` turns a bucket off |
| `AGNOSTIC_GATEWAY__MAX_BODY_MB` | `100` | largest request body streamed to a runtime |
| `AGNOSTIC_GATEWAY__HEARTBEAT_SECONDS` | `15` | SSE keep-alive comments while a runtime is quiet |
| `AGNOSTIC_GATEWAY__UPSTREAM_READ_TIMEOUT` | `600` | seconds a runtime may stay silent mid-response |
| `AGNOSTIC_GATEWAY__CIRCUIT_FAILURES` / `__CIRCUIT_COOLDOWN_SECONDS` | `5` / `30` | consecutive connection failures before failing fast, and for how long |
| `AGNOSTIC_AUDIT__RETENTION_DAYS` | `400` | older monthly partitions are dropped (ADR-017) |
| `AGNOSTIC_AUDIT__MAINTENANCE_CRON` | `17 3 * * *` | partition creation and retention |

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

## Operate (P02)

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_APPROVALS__POLL_SECONDS` | `15` | how often one replica reads each instance's pending-approval count (`0` turns the poller off) |
| `AGNOSTIC_APPROVALS__CONTINUE_RETRY_DELAYS` | `[0.5, 1.0, 2.0]` | backoff (seconds) while AgentOS answers 409 to a continuation |
| `AGNOSTIC_OBSERVE__MAX_TRACE_PAGES` | `10` | pages of 100 traces scanned per overview (error rate, p95, per-component runs) |
| `AGNOSTIC_OBSERVE__WARM_CRON` | `* * * * *` | recompute the 7-day overview of connected instances; empty turns it off |
| `AGNOSTIC_SEARCH__REINDEX_CRON` | `*/5 * * * *` | rebuild the ⌘K index; empty turns it off |
| `AGNOSTIC_NOTIFICATIONS__HEARTBEAT_SECONDS` | `15` | keepalive interval on `/api/v1/events` |
| `AGNOSTIC_NOTIFICATIONS__MAX_STREAM_SECONDS` | `1800` | streams end after this; browsers reconnect with `Last-Event-ID` |

## Tests only

| Variable | Meaning |
|---|---|
| `AGNOSTIC_TEST_DATABASE_URL`, `AGNOSTIC_TEST_REDIS_URL` | use existing servers instead of testcontainers |
| `AGNOSTIC_TEST_REDIS_IMAGE` | cache image for testcontainers (Valkey/Dragonfly compatibility) |
| `AGNOSTIC_CONTRACT_RUNTIME_URL` | runtime for contract tests |
