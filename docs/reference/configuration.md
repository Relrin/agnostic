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
| `AGNOSTIC_GATEWAY__MAX_UPLOAD_MB` | `1024` | largest file upload (`POST /knowledge/content`), streamed without buffering |
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
| `AGNOSTIC_OBSERVE__MAX_SPAN_STAT_TRACES` | `100` | newest traces whose spans feed "Slowest span types" |
| `AGNOSTIC_OBSERVE__SPAN_STATS_TTL_SECONDS` | `900` | how long span statistics are reused per instance and window |
| `AGNOSTIC_OBSERVE__MAX_SESSION_PAGES` | `20` | pages of 100 sessions read for per-component usage on the Metrics page; beyond that it says *approximate* |
| `AGNOSTIC_OBSERVE__COMPARISON_CACHE_DAYS` | `7` | trace comparisons are recomputed after this many days |
| `AGNOSTIC_EVALS__CONCURRENCY` | `4` | eval runs in flight per batch; batches on one instance run one after another |
| `AGNOSTIC_CONTEXT__DUPLICATE_THRESHOLD` | `0.35` | trigram similarity (0 to 1) above which two memories of one user are flagged "likely duplicate" |
| `AGNOSTIC_CONTEXT__MAX_DUPLICATE_SCAN` | `500` | newest memories of one user compared for duplicates |
| `AGNOSTIC_CONTEXT__MAX_CONTENT_PAGES` | `10` | pages of 100 knowledge content rows filtered and counted per request |
| `AGNOSTIC_CONTEXT__PROVENANCE_SESSIONS` | `10` | sessions searched for the run a memory came from |
| `AGNOSTIC_CONTEXT__PROVENANCE_TRACES` | `50` | newest traces searched for file writes when the instance has no agnostic-bridge |
| `AGNOSTIC_SEARCH__REINDEX_CRON` | `*/5 * * * *` | rebuild the ⌘K index; empty turns it off |
| `AGNOSTIC_NOTIFICATIONS__HEARTBEAT_SECONDS` | `15` | keepalive interval on `/api/v1/events` |
| `AGNOSTIC_NOTIFICATIONS__MAX_STREAM_SECONDS` | `1800` | streams end after this; browsers reconnect with `Last-Event-ID` |

## Control: approvals, notifications, scheduler, queue

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_APPROVALS__WATCH_CRON` | `* * * * *` | when the approvals watcher routes new approvals, sends expiry reminders and enforces expiry; empty turns it off |
| `AGNOSTIC_APPROVALS__SCAN_LIMIT` | `500` | newest approvals per status that the inbox (tool and text filters, the Expired tab, counts) and the watcher look at |
| `AGNOSTIC_APPROVALS__EXPIRING_LEAD_MINUTES` | `60` | how long before an approval's expiry the routed people get a reminder |
| `AGNOSTIC_NOTIFICATIONS__SLACK_API_BASE` | `https://slack.com/api` | Slack Web API base; a channel's own `api_base` wins (the development Slack mock is `http://localhost:8030/api`) |
| `AGNOSTIC_NOTIFICATIONS__HTTP_TIMEOUT_SECONDS` | `10` | timeout of one Slack or webhook request |
| `AGNOSTIC_NOTIFICATIONS__DELIVERY_RETRIES` | `4` | retries of a failed email, Slack or webhook delivery (the `notifications` job queue) before it is marked failed |
| `AGNOSTIC_SCHEDULER__WATCH_CRON` | `* * * * *` | when the failure watcher looks for failed scheduled runs; empty turns it off |

Org settings (changed in the app, stored by the `settings` module): `approval_ttl_hours` (default `0`, never) gives
approvals without their own expiry one. Whether expiry stops runs is decided per instance, in Settings › Approvals.

## Access governance: directory, service accounts, audit

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_ACCESS__EXPIRY_CRON` | `*/5 * * * *` | when expired bindings (temporary access, invitations with an end date) are removed; empty turns it off |
| `AGNOSTIC_DIRECTORY__GOOGLE_SYNC_CRON` | `*/15 * * * *` | Google Workspace group sync (only while it is turned on in the app) |
| `AGNOSTIC_DIRECTORY__RECONCILE_CRON` | `17 * * * *` | group memberships reconciled with deprovisioned accounts and mapping rules |
| `AGNOSTIC_SERVICE_ACCOUNTS__TOKEN_PEPPER` | derived from the master key | mixed into gateway token hashes; changing it invalidates every gateway token |
| `AGNOSTIC_SERVICE_ACCOUNTS__POLL_CRON` | `*/5 * * * *` | native tokens' last use read from each instance; expired accounts swept |
| `AGNOSTIC_SERVICE_ACCOUNTS__LAST_USED_WRITE_SECONDS` | `60` | how often a gateway token's last use is written |
| `AGNOSTIC_AUDIT__RETENTION_DAYS` | `400` | hot retention until the audit policy is saved in the app |
| `AGNOSTIC_AUDIT__MAINTENANCE_CRON` | `17 3 * * *` | partitions, archive, restored months and expired exports |
| `AGNOSTIC_AUDIT__DELIVER_CRON` / `__DELIVER_ON_RECORD` | `* * * * *` / `true` | SIEM delivery: periodic, plus queued a few seconds after events are written |
| `AGNOSTIC_AUDIT__SETTLE_SECONDS` / `__DELIVERY_BATCH` | `5` / `500` | events younger than this wait for the next delivery; events per batch |
| `AGNOSTIC_AUDIT__EXPORT_SYNC_LIMIT` | `10000` | above this many events, exports run as a background job |
| `AGNOSTIC_GATEWAY__INGEST_CRON` | `* * * * *` | AgentOS authorization trails (`/authz/decisions`, `/authz/audit`) copied into the audit log |

In the app (stored in the database): sign-in providers and the auth policy (*Organization › Authentication*), SCIM
tokens, mapping rules, deprovisioning and Google sync (*Directory sync*), audit retention, archive target and hash
chain (*Audit retention*), SIEM destinations, and the org setting `temporary_access_max_hours` (default `168`).

## Code sources

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_SOURCES__GIT_BINARY` | `git` | the git executable workers run (2.36 or newer) |
| `AGNOSTIC_SOURCES__MIRRORS_DIR` | `var/sources/mirrors` | bare mirrors of source repositories; give it its own volume |
| `AGNOSTIC_SOURCES__MIRROR_QUOTA_MB` / `__TOTAL_QUOTA_MB` | `512` / `10240` | per source (the source turns `over_quota`) and for all mirrors (a warning) |
| `AGNOSTIC_SOURCES__GIT_TIMEOUT_SECONDS` / `__FETCH_TIMEOUT_SECONDS` | `30` / `180` | one git call; a fetch, a push or reading a file the mirror doesn't have yet |
| `AGNOSTIC_SOURCES__PROVIDER_TIMEOUT_SECONDS` | `15` | one call to a git host's API |
| `AGNOSTIC_SOURCES__MAX_CHANGED_FILES` / `__MAX_FILE_BYTES` | `500` / `256000` | changed mapped files read per fetch; larger files aren't read |
| `AGNOSTIC_SOURCES__ALLOW_FILE_REMOTES` | `false` | accept `file://` clone URLs (tests, air-gapped mirrors) |
| `AGNOSTIC_SOURCES__LOCAL_ROOTS` | `[]` | folders local sources may point into (development instances only); empty turns local sources off |
| `AGNOSTIC_SOURCES__WATCH_LOCAL` / `__WATCH_DEBOUNCE_MS` | `true` / `800` | watch local folders for changes |
| `AGNOSTIC_SOURCES__FETCH_CRON` | `*/15 * * * *` | fetch sources without a webhook; empty turns it off |
| `AGNOSTIC_SOURCES__PULL_REQUEST_CRON` | `*/5 * * * *` | check open pull requests; empty turns it off |
| `AGNOSTIC_SOURCES__GC_CRON` | `41 3 * * *` | pack mirrors, remove orphaned ones, prune webhook deliveries |
| `AGNOSTIC_SOURCES__WEBHOOK_BASE_URL` | the public URL | where git hosts post webhooks (`{url}/hooks/{provider}`); no webhook is registered without a public URL |
| `AGNOSTIC_SOURCES__WEBHOOK_MAX_BYTES` / `__DELIVERY_RETENTION_DAYS` | `5000000` / `30` | largest webhook body; how long deliveries are kept |
| `AGNOSTIC_SOURCES__COMMITTER_NAME` / `__COMMITTER_EMAIL` | `Agnostic Studio` / `studio@agnostic.invalid` | the committer of Studio's commits (the author is the person) |
| `AGNOSTIC_SOURCES__GITHUB_API_URL` / `__GITHUB_WEB_URL` | `https://api.github.com` / `https://github.com` | GitHub defaults; a connection's own URLs (Enterprise Server) win |
| `AGNOSTIC_SOURCES__GITHUB_APP_SLUG` | — | the GitHub App people install for read & write sources |

## Assistant

| Variable | Default | Meaning |
|---|---|---|
| `AGNOSTIC_ASSISTANT__ANSWER_TIMEOUT_SECONDS` | `120` | an answer still being written after this long is stopped and marked failed |
| `AGNOSTIC_ASSISTANT__TOOL_TIMEOUT_SECONDS` / `__MAX_TOOL_CALLS` | `30` / `12` | one tool call; tool calls per answer |
| `AGNOSTIC_ASSISTANT__MAX_TOOL_RESULT_CHARS` | `12000` | a tool result longer than this is cut before the model reads it |
| `AGNOSTIC_ASSISTANT__HISTORY_MESSAGES` | `10` | earlier messages sent with a follow-up question |
| `AGNOSTIC_ASSISTANT__MAX_ATTACHMENTS` / `__MAX_ATTACHMENT_BYTES` / `__MAX_ATTACHMENT_CHARS` | `4` / `2000000` / `20000` | files per question, size of each, text kept from each (logs keep their end) |
| `AGNOSTIC_ASSISTANT__MAX_QUESTION_CHARS` | `4000` | longest question; attach longer text |
| `AGNOSTIC_ASSISTANT__PRUNE_CRON` | `23 4 * * *` | delete conversations past the org's retention; empty turns it off |

The provider, models, API key, budgets, rate limit, redaction and retention are org settings
(Organization › AI features, `GET`/`PUT /api/v1/assistant/settings`), not environment variables; see
[configure AI features](../how-to/configure-ai-features.md).

## Tests only

| Variable | Meaning |
|---|---|
| `AGNOSTIC_TEST_DATABASE_URL`, `AGNOSTIC_TEST_REDIS_URL` | use existing servers instead of testcontainers |
| `AGNOSTIC_TEST_REDIS_IMAGE` | cache image for testcontainers (Valkey/Dragonfly compatibility) |
| `AGNOSTIC_CONTRACT_RUNTIME_URL` | runtime for contract tests |
| `AGNOSTIC_TEST_ASSISTANT_MODEL`, `AGNOSTIC_TEST_ASSISTANT_ENDPOINT`, `AGNOSTIC_TEST_ASSISTANT_API_KEY` | the model the assistant Q&A suite (`-m assistant_eval`) asks |
