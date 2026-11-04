# CLI reference

`agnostic` is installed with the backend (`cd backend && uv run agnostic …`; `python -m agnostic_server` is the
same). Every command reads the same settings as the server ([configuration](configuration.md)). Code:
`backend/apps/agnostic-server/src/agnostic_server/` (`cli.py`, `tokens.py`, `audit_cli.py`, `secrets_cli.py`).

## Server and database

| Command | Does |
|---|---|
| `agnostic api [--host H] [--port P] [--reload]` | serve the HTTP API (uvicorn; one process per container) |
| `agnostic worker [-q QUEUE]… [--concurrency N]` | run background jobs and periodic schedules; PostgreSQL only (exit 2 on SQLite) |
| `agnostic dev` | API with reload, plus a worker restarted on code changes (embedded job mode: API only) |
| `agnostic migrate` | apply every pending migration (the image's one-shot command; same as `db upgrade`) |
| `agnostic db upgrade [REVISION]` | apply migrations of the kernel and every installed module (default `heads`) |
| `agnostic db upgrade --check` | apply pending migrations in one transaction, print each revision's time, roll back (PostgreSQL only, exit 2 otherwise); run it against a copy of production before upgrading |
| `agnostic db downgrade REVISION` | revert to a revision, e.g. `gateway@base` or `base` |
| `agnostic db current` | print the migration state (below) |
| `agnostic config check [--connect]` | effective configuration with secrets redacted, then enabled modules and the job mode; `--connect` probes the database, cache, migrations, master key, OTLP, SMTP and each module's endpoints (sign-in providers, the audit archive, runtimes, …) and exits 1 on a failure |
| `agnostic modules list` | installed modules: version, enabled/disabled, dependencies, routes, jobs, assistant tools |
| `agnostic openapi [--out FILE]` | write the OpenAPI document (stdout by default) |
| `agnostic bootstrap --org-name NAME` | first run: names the org and prints a one-time link (24 h) where the first Owner signs up |
| `agnostic bootstrap --org-name NAME --owner-email E [--owner-name N] [--password-stdin]` | creates the first Owner directly (asks for the password, or reads one line from stdin) |

`db upgrade`, `db downgrade` and `db current` end with the state after the operation:

```text
current: a0001_audit_events, b0001_assistant, …          (or "(empty)")
heads:   a0001_audit_events, b0001_assistant, …
pending: g0001_gateway                                     (only when something is pending)
status:  up to date                                        (or "pending migrations")
```

## Service accounts

| Command | Does |
|---|---|
| `agnostic tokens create NAME --instance SLUG… (--role R [--extra-scopes …] \| --scopes …) [--description TEXT] [--expires-in 90d\|30d\|365d\|never] [--kind native] [--kind gateway] [--forwards-user-id] [--created-by EMAIL] [--yes-privileged]` | create a service account and print its tokens once (native per instance, gateway). Defaults: `--expires-in 90d`, `--kind native`. `--yes-privileged` confirms write, delete or admin scopes |
| `agnostic tokens list` | service accounts with their scopes, instances and token prefixes |
| `agnostic tokens revoke NAME [--token PREFIX]` | revoke one token, or delete the account and revoke all of them |

## Audit

| Command | Does |
|---|---|
| `agnostic audit verify [--since ISO] [--until ISO]` | check the audit hash chain (`--since` inclusive, `--until` exclusive); exits 1 when it is broken |
| `agnostic audit restore YYYY-MM` | bring an archived month back into the database for 7 days (verified first, chain included) |
| `agnostic audit archives list` | archived months: events, size, archive date, restore window |
| `agnostic audit archives verify (YYYY-MM \| --all)` | download archived months and check them against their manifests and the database record (SHA-256, size, count, month bounds, hash chain up to the chain head); exits 1 when one is damaged |

## Secrets

| Command | Does |
|---|---|
| `agnostic secrets generate-key [--provider P]` | print a new master key (wrapped by the KMS for a KMS provider) |
| `agnostic secrets wrap-key --to P` | re-wrap the configured current and previous master keys for another provider or KMS key version |
| `agnostic secrets status` | which master key every stored secret is sealed with; exits 1 when one needs an unconfigured key |
| `agnostic secrets rotate` | re-seal every stored secret with the current master key (safe to run again) |

Exit codes: `0` success, `1` a failed check or a module graph error, `2` a usage error.
