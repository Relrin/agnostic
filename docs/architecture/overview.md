# Architecture overview

Agnostic is a **control plane** for Agno AgentOS. AgentOS already serves runs, sessions, memory, knowledge, traces,
approvals, schedules and components over REST/SSE; Agnostic doesn't re-implement them. It owns identity, policy,
the instance registry, Studio and git sync, cross-instance views and audit, and talks to each AgentOS over HTTP.

![System overview: browser, api and worker, PostgreSQL and Redis, AgentOS instances](images/system-overview.svg)

## Processes

One codebase, one image (`agnostic` CLI in `backend/apps/agnostic-server`):

| Process | Command | Does |
|---|---|---|
| api | `agnostic api` | HTTP API under `/api/v1`, `/healthz` and `/readyz`, the AgentOS gateway, and the built web app when `AGNOSTIC_HTTP__WEB_DIR` is set |
| worker | `agnostic worker` | Procrastinate jobs and periodic schedules from every module |
| migrate | `agnostic db upgrade` | one-shot schema migration before a rollout |

`agnostic dev` runs api and worker with auto-reload. With SQLite the worker runs inside the API process, so a
development install is one process.

## Dependencies are endpoints

Agnostic ships only its own artifacts. PostgreSQL, Redis (or Valkey/DragonflyDB), SMTP, object storage, the IdP and
the AgentOS runtimes are endpoints the operator configures, each with TLS options; `agnostic config check
--connect` and `/readyz` probe them.

## Data ownership

Runtime data (sessions, traces, memories, …) stays in AgentOS. The control plane keeps control data (users, roles,
instances, audit, Studio metadata) in the `agnostic` schema, durable jobs in the `procrastinate` schema, and only
ephemeral state in Redis: losing Redis costs caches, sessions and live updates, never data.

## Repository layout

![Repository layout: top-level directories, backend packages, modules and apps, frontend apps, packages and modules](images/repository-layout.svg)

| Path | What |
|---|---|
| `backend/` | uv workspace, Python 3.15 |
| `backend/packages/agnostic-kernel` | shared kernel, no business logic ([backend kernel](backend-kernel.md)) |
| `backend/packages/agnostic-agentos-client` | typed AgentOS 3.1.x client |
| `backend/packages/agnostic-spec`, `agnostic-cel`, `agnostic-codegen` | typed component configs, workflow CEL, config ⇄ Python ([Studio](studio.md)) |
| `backend/modules/*` | 21 feature modules: `access`, `approvals`, `assistant`, `audit`, `context`, `directory`, `evals`, `gateway`, `identity`, `instances`, `notifications`, `observe`, `org`, `queue`, `scheduler`, `search`, `service_accounts`, `settings`, `sources`, `studio`, `system` ([module system](module-system.md)) |
| `backend/apps/agnostic-server` | composition root: app factory, worker, CLI |
| `backend/tests/` | `unit`, `api`, `integration`, `contract`, `assistant_eval`, golden fixtures |
| `frontend/` | Yarn 4 workspaces: React 19, Vite, Tailwind v4 ([frontend](frontend.md)) |
| `frontend/apps/web` | the shell: router, sidebar, header, command palette |
| `frontend/packages/*` | `ui`, `core`, `api`, `testing`, `assistant`, `editor`, `studio` |
| `frontend/modules/*` | 30 page modules (identity and account, instances, settings, org settings, system, help, people, roles, service accounts, audit, home, chat, sessions, traces, metrics, evals, memory, knowledge, learnings, files, approvals, scheduler, queue, Studio editors, registry, sources, assistant) |
| `runtime/` | `agnostic-runtime`: reference AgentOS (Python 3.13, agno 3.1.12) |
| `bridge/` | `agnostic-bridge`: optional routes customers add to their AgentOS ([runtime and client](agentos-runtime-and-client.md)) |
| `deploy/dev` | Compose for contributors: PostgreSQL, Redis, Mailpit, a Slack mock, Keycloak, SeaweedFS, Gitea, Ollama, Vault (some behind profiles) |
| `deploy/compose` | the Compose file that runs the `agnostic` image against your endpoints |
| `scripts/` | repository tooling: license checks, SSE fixture recording, upgrade and restore drills, air-gap kit |
| `docs/` | these pages, how-to guides, reference, in-product guides |

## Where to go next

- [Backend kernel](backend-kernel.md) and [module system](module-system.md)
- [Frontend](frontend.md)
- [AgentOS runtime and client](agentos-runtime-and-client.md)
- [Identity, access and the gateway](identity-access-gateway.md), then [access governance](access-governance.md)
- [Operate](operate-and-realtime.md), [control](control.md), [observe](observe-and-evals.md),
  [context](context.md), [Studio](studio.md), [code sources](sources.md), [assistant](assistant.md)
