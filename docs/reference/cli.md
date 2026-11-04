# CLI reference

`agnostic` is installed with the backend (`cd backend && uv run agnostic …`). Every command reads the same
settings as the server ([configuration](configuration.md)).

| Command | Does |
|---|---|
| `agnostic api [--host H] [--port P] [--reload]` | serve the HTTP API (uvicorn; one worker per container) |
| `agnostic worker [-q QUEUE]… [--concurrency N]` | run background jobs and periodic schedules; PostgreSQL only |
| `agnostic dev` | API with reload + worker restarted on code changes (SQLite: API only, jobs embedded) |
| `agnostic migrate` | apply every pending migration (the image's one-shot command; same as `db upgrade`) |
| `agnostic db upgrade [REVISION]` | apply migrations of the kernel and every installed module (default `heads`) |
| `agnostic db upgrade --check` | apply pending migrations in one transaction, print each revision's time, roll back (PostgreSQL only); run it against a copy of production before upgrading |
| `agnostic db downgrade REVISION` | revert to a revision, e.g. `gateway@base` or `base` |
| `agnostic db current` | applied revisions, heads and pending revisions |
| `agnostic config check [--connect]` | effective configuration with secrets redacted; `--connect` probes every endpoint (database, cache, migrations, master key, SMTP, OTLP, sign-in providers, the audit archive, every runtime) and exits 1 on a failure |
| `agnostic modules list` | installed modules: version, enabled/disabled, dependencies, routes, jobs |
| `agnostic openapi [--out FILE]` | write the OpenAPI document (stdout by default) |
| `agnostic bootstrap --org-name NAME` | first run: names the org and prints a one-time link (24 h) where the first Owner signs up |
| `agnostic bootstrap --org-name NAME --owner-email E [--owner-name N] [--password-stdin]` | creates the first Owner directly (asks for the password, or reads it from stdin); handy for single-person installs |
| `agnostic tokens create NAME --instance SLUG… (--role R [--extra-scopes …] \| --scopes …) [--expires-in 90d\|30d\|365d\|never] [--kind native] [--kind gateway] [--forwards-user-id] [--created-by EMAIL] [--yes-privileged]` | create a service account and print its tokens once (native per instance, gateway) |
| `agnostic tokens list` | service accounts with their scopes, instances and token prefixes |
| `agnostic tokens revoke NAME [--token PREFIX]` | revoke one token, or delete the account and revoke all of them |
| `agnostic audit verify [--since ISO] [--until ISO]` | check the audit hash chain; exits 1 when it is broken |
| `agnostic audit restore YYYY-MM` | bring an archived month back into the database for 7 days (verified first, chain included) |
| `agnostic audit archives list` | archived months: events, size, archive date, restore window |
| `agnostic audit archives verify (YYYY-MM \| --all)` | download archived months and check them against their manifests and the database record (SHA-256, size, count, month bounds, hash chain up to the chain head); exits 1 when one is damaged |
| `agnostic secrets generate-key [--provider P]` | print a new master key (wrapped by the KMS for a KMS provider) |
| `agnostic secrets wrap-key --to P` | re-wrap the configured current and previous master keys for another provider or KMS key version |
| `agnostic secrets status` | which master key every stored secret is sealed with; exits 1 when one needs an unconfigured key |
| `agnostic secrets rotate` | re-seal every stored secret with the current master key (safe to run again) |


Exit codes: `0` success, `1` a check or graph error, `2` a usage error (including `worker` on SQLite).

`python -m agnostic_server` is equivalent to `agnostic`.
