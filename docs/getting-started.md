# Getting started

From a fresh clone to a running stack and a first change. Install the tools in the
[README prerequisites](../README.md#prerequisites) first.

## 1. Run it

```bash
just setup         # .env, Python and Node dependencies from the lockfiles
just up            # PostgreSQL, Redis, Mailpit and the Slack mock (deploy/dev/compose.yml)
just migrate       # kernel and every installed module
just bootstrap     # the org and its first Owner (daniel@localhost.company / localhost-dev-password, see .env)
just dev           # API + worker (:8000) and the web app (:5173)
just check-config  # effective config, then every endpoint probed
```

`database`, `cache` and `migrations` should be `ok`. If `migrations` says "unknown revision in the database", the
database was migrated by an older pre-release build: recreate it (`just nuke && just up && just migrate`).

## 2. Look around

| URL | What |
|---|---|
| <http://localhost:5173> | the web app; sign in as the Owner. **Instances › Connect** adds an AgentOS (`just runtimes` + `just seed` do it for two [reference runtimes](how-to/reference-runtimes.md)) |
| <http://localhost:8025> | Mailpit: invitation and password-reset emails |
| <http://localhost:8000/api/v1/docs> | interactive API docs (OpenAPI at `/api/v1/openapi.json`) |
| <http://localhost:8000/readyz> | readiness: database, cache, migrations |
| <http://localhost:6006> | `just storybook`: the design system, including the **Tokens** page |

A nav entry whose module is disabled, or whose capability the instance lacks, opens an "unavailable" page.

## 3. Follow one request end to end

1. On **People**, invite someone (*Send by email*). The page calls `POST /api/v1/invitations` through the generated
   client (`@agnostic/api`), which adds the `X-CSRF-Token` header next to the session cookie.
2. The identity module turns the cookie into a `Principal`. `InvitePerson`
   (`backend/modules/org/src/agnostic_org/application/invitations.py`) asks the access module's `Authorizer` for
   `org:members:write`, stores the invitation with only the SHA-256 hash of its token, records `invitations.create`
   in the audit log in the same transaction, commits, then emails the link (Mailpit). The response carries the
   `accept_url` once and `email_sent`.
3. Open the link in a private window and accept: the account, the membership and the invitation's role bindings
   and groups are created, and a session starts.
4. **Audit log** shows each step, with who did what.

*Create link only* skips the email: copy the link from the dialog. *Copy new link* on a pending invitation issues a
new one (`POST /api/v1/invitations/{id}/link`); the old link stops working.

That path touches every layer a module uses; [module system](architecture/module-system.md) explains them.

## 4. Make a change

- Add a field to the API: change the Pydantic schema, then `just api-gen` to refresh the TypeScript client and
  `docs/reference/api.md`.
- Add a table: [write a migration](how-to/migrations.md).
- Add a page: [add a frontend module](how-to/add-frontend-module.md).

Run `just check` before you push.

## Without Docker

Put `AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db` in `.env` and skip `just up`. Migrations, the API and the web app
work the same; jobs run inside the API process (in memory: queued jobs are lost on restart), and sessions, caches and
rate limits stay in that process. Redis is still tried for job progress events; without it readiness reports the
cache down and everything else keeps working.
