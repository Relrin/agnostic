# Troubleshooting

## Windows

- **`just` says `sh` isn't found.** Install Git for Windows and make sure its `usr\bin` (or `bin`) is on `PATH`;
  the justfile runs recipes with `sh` on every OS.
- **`NotImplementedError` / "Psycopg cannot use the 'ProactorEventLoop'".** Something started an event loop
  without `agnostic_server.loops.new_event_loop`. Use the `agnostic` CLI (it selects a selector loop) rather than
  running uvicorn directly, or pass `--loop agnostic_server.loops:new_event_loop`.
- **`localhost:5173` works but `127.0.0.1:5173` doesn't.** Vite listens on `localhost`, which resolves to IPv6
  first on Windows. Use `http://localhost:5173`.
- **Line endings.** `.gitattributes` keeps text files LF; editors should respect `.editorconfig`.

## Docker and the dev stack

- **Port 5432 or 6379 is taken.** Set `AGNOSTIC_DEV_POSTGRES_PORT` / `AGNOSTIC_DEV_REDIS_PORT` before `just up`
  and point `AGNOSTIC_DATABASE__URL` / `AGNOSTIC_REDIS__URL` at the new ports.
- **Port 1025 or 8025 is taken** (Mailpit SMTP, Mailpit UI). Set `AGNOSTIC_DEV_SMTP_PORT` or
  `AGNOSTIC_DEV_MAILPIT_PORT`, and change `AGNOSTIC_SMTP__URL` to match.
- **A runtime answers 401 after `just seed`.** Its key in `runtime/.jwt/` is from another control-plane database
  (you reset it, or rotated a key). Run `just seed` again and restart `just runtimes`.
- **`agentos_prod` doesn't exist.** The init script runs only on a new volume: `just nuke && just up`.
- **No Docker at all.** Use SQLite (`AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db`) and skip `just up`; Redis is
  optional for development (readiness will report it as down).

## Backend

- **`/readyz` says "pending migrations".** Run `just migrate`.
- **"unknown revision in the database"** (`/readyz`, `config check --connect`, or an error from `db current`). The
  database was migrated by a pre-release build whose revisions this code doesn't ship. Recreate it:
  `just nuke && just up && just migrate` ([migrations](migrations.md#pre-release-databases)).
- **`test_migrations_schema.py` fails.** The migrated schema and the table models differ; the assertion lists the
  differences ([migrations](migrations.md#guard-tests)).
- **Invitation emails never arrive.** Without `AGNOSTIC_SMTP__URL` they go to the API log; with it, a failed send
  returns `email_sent: false` and the link (shown once in the dialog) still works. Later, *Copy new link* on the
  pending invitation issues a fresh one to share.
- **`cannot disable unknown module(s)`.** A name in `AGNOSTIC_MODULES__DISABLED` isn't installed; check
  `agnostic modules list`.
- **`A separate worker needs PostgreSQL`.** You're on SQLite; jobs already run inside `agnostic api`.
- **`PydanticUserError: … is not fully defined` on a route.** The router module uses
  `from __future__ import annotations`; remove it (see [backend kernel](../architecture/backend-kernel.md)).

## Code sources

- **"The git executable 'git' isn't installed where the worker runs"**: install git (2.36 or newer) in the image
  that serves the `git` queue, or point `AGNOSTIC_SOURCES__GIT_BINARY` at it.
- **A source turns `over_quota`**: narrow its path mappings (or use a smaller branch), or raise
  `AGNOSTIC_SOURCES__MIRROR_QUOTA_MB`.
- **"refused the connection's credentials"**: the token expired or lost access; update the connection (secrets are
  replaced only when given) and *Verify* it. A GitHub App says "isn't installed yet" until it is installed.
- **Webhooks answer 401**: the delivery isn't signed with the source's secret (re-adding the source registers a new
  one) or the repository name differs. Check *deliveries* on the source; nothing is stored for refused deliveries.
- **Nothing arrives after a push**: the git host can't reach `/hooks/<provider>` (check the reverse proxy and
  `AGNOSTIC_SOURCES__WEBHOOK_BASE_URL`); the periodic fetch still picks the push up.

## Frontend

- **"All versions satisfying … are quarantined".** The version was published too recently; pin the previous
  release.
- **Stale API types after a backend change.** `just api-gen`.
- **Playwright can't find a browser.** `cd frontend && yarn workspace @agnostic/web playwright install chromium`.
