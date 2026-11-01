# Getting started

This walks you from a fresh clone to a running stack and a first change. Install the tools in the
[README prerequisites](../README.md#prerequisites) first.

## 1. Run it

```bash
just setup      # .env, Python and Node dependencies from the lockfiles
just up         # PostgreSQL, Redis and Mailpit (deploy/dev/compose.yml)
just migrate    # schema for the kernel and every installed module
just bootstrap  # the org and its first Owner (daniel@localhost.company / localhost-dev-password, see .env)
just dev        # API + worker (:8000) and the web app (:5173)
```

Check the endpoints the API depends on:

```bash
just check-config
```

You should see `database`, `cache` and `migrations` marked `ok`.

## 2. Look around

- <http://localhost:5173>: sign in as the Owner. Every page of the design is in the sidebar; pages whose module
  ships later say which phase delivers them. **Instances › Connect** adds an AgentOS: `just runtimes` starts two
  reference ones and `just seed` connects them ([reference runtimes](how-to/reference-runtimes.md)).
- <http://localhost:8025>: Mailpit, where invitation and password-reset emails land.
- <http://localhost:8000/api/v1/docs>: interactive API docs (OpenAPI at `/api/v1/openapi.json`).
- <http://localhost:8000/readyz>: readiness (database, cache, migrations).
- `just storybook` → <http://localhost:6006>: the design system, including the **Tokens** page.

## 3. Follow one request end to end

1. On **People**, invite someone. The page calls `POST /api/v1/invitations` through the generated client
   (`@agnostic/api`), which adds the `X-CSRF-Token` header next to the session cookie.
2. The identity module turns the cookie into a `Principal`; `InvitePerson`
   (`backend/modules/org/.../application/invitations.py`) asks the access module's `Authorizer` for
   `org:members:write`, stores the invitation, records `invitations.create` in the audit log in the same
   transaction, and emails the link (Mailpit).
3. Open the link in a private window and accept: the account, the membership and the invitation's role bindings
   are created, and a session starts.
4. **Audit log** shows every step, with who did what.

That path touches every layer a real module uses; [module system](architecture/module-system.md) explains it.

## 4. Make a change

- Add a field to the API: change the Pydantic schema, then `just api-gen` to refresh the TypeScript client.
- Add a table: [write a migration](how-to/migrations.md).
- Add a page: [add a frontend module](how-to/add-frontend-module.md).

Run `just check` before you push.

## Without Docker

Put `AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db` in `.env`. Migrations, the API and the web app work the
same; jobs run inside the API process, and sessions and caches stay in that process. Redis is still used for job progress events and readiness, but losing it
only degrades those (readiness reports it, jobs keep working).
