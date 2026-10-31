# Getting started

This walks you from a fresh clone to a running stack and a first change. Install the tools in the
[README prerequisites](../README.md#prerequisites) first.

## 1. Run it

```bash
just setup      # .env, Python and Node dependencies from the lockfiles
just up         # PostgreSQL + Redis (deploy/dev/compose.yml)
just migrate    # schema for the kernel and every installed module
just dev        # API + worker (:8000) and the web app (:5173)
```

Check the endpoints the API depends on:

```bash
just check-config
```

You should see `database`, `cache` and `migrations` marked `ok`.

## 2. Look around

- <http://localhost:5173>: the shell. Every page of the design is in the sidebar; pages whose module ships later
  say which phase delivers them. **Hello** is the one working sample page.
- <http://localhost:8000/api/v1/docs>: interactive API docs (OpenAPI at `/api/v1/openapi.json`).
- <http://localhost:8000/readyz>: readiness (database, cache, migrations).
- `just storybook` → <http://localhost:6006>: the design system, including the **Tokens** page.

## 3. Follow one request end to end

1. Type a greeting on the Hello page and send it.
2. The page calls `POST /api/v1/hello/greetings` through the generated client (`@agnostic/api`).
3. `CreateGreeting` (`backend/modules/hello/.../application/use_cases.py`) stores it and defers the
   `hello.compose_reply` job.
4. The worker runs the job, which writes the reply and reports progress to `kernel_job_progress` and Redis.
5. The page polls while the greeting is pending and shows the reply.

That path touches every layer a real module uses; [module system](architecture/module-system.md) explains it.

## 4. Make a change

- Add a field to the API: change the Pydantic schema, then `just api-gen` to refresh the TypeScript client.
- Add a table: [write a migration](how-to/migrations.md).
- Add a page: [add a frontend module](how-to/add-frontend-module.md).

Run `just check` before you push.

## Without Docker

Put `AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db` in `.env`. Migrations, the API and the Hello page work the
same; jobs run inside the API process. Redis is still used for job progress events and readiness, but losing it
only degrades those (readiness reports it, jobs keep working).
