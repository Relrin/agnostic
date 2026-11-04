# Agnostic

A self-hosted control plane for [Agno](https://github.com/agno-agi/agno) AgentOS runtimes: identity and access,
instance management, operations, observability, and a UI for agents, teams and workflows. It runs inside your
network and talks to every AgentOS over its REST/SSE API.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.13.6 | installs Python 3.15.2 (control plane) and 3.13 (reference runtime) for you |
| Node.js | 26.13.0 (Active LTS; `.nvmrc`) | 24.11+ works for local development |
| Yarn | 4.18.1 | bundled in `frontend/.yarn/releases`; any global `yarn` delegates to it |
| Docker | with Compose v2 | for PostgreSQL, Redis and Mailpit; optional if you use SQLite |
| [just](https://just.systems) | 1.59.0 | `uv tool install rust-just==1.59.0` |
| Git | any | on Windows, Git for Windows provides the `sh` that `just` uses |

## Build and run from scratch

```bash
git clone <this repository> agnostic && cd agnostic
just setup      # .env from .env.example; uv sync (backend, runtime, bridge); yarn install (all from lockfiles)
just up         # PostgreSQL 18 (+pgvector), Redis 8, Mailpit and a Slack mock (deploy/dev/compose.yml)
just migrate    # kernel and every installed module
just bootstrap  # org "Localhost Company" and its Owner (AGNOSTIC_DEV_OWNER_EMAIL / _PASSWORD in .env)
just dev        # API + worker on :8000, web app on :5173
```

Open <http://localhost:5173> and sign in as the Owner. To create a different Owner, run
`cd backend && uv run agnostic bootstrap --org-name "…" --owner-email you@example.com`, or leave out
`--owner-email` and open the one-time setup link it prints.

`just runtimes` starts two reference AgentOS instances (`dev-prod` on :7777, `dev-staging` on :7778) and `just seed`
connects them ([reference runtimes](docs/how-to/reference-runtimes.md)). Sign-in with GitHub, GitLab, Google, Okta,
any OIDC or SAML provider: [sign-in providers](docs/how-to/sign-in-providers.md).

No Docker? Set `AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db` in `.env`, then `just migrate && just bootstrap &&
just dev`. Jobs run inside the API process in that mode ([configuration](docs/how-to/configuration.md)).

## Checks

```bash
just check      # lint, types, unit + integration tests, API client drift, licenses
just test-ui    # Storybook a11y tests and Playwright e2e
just --list     # everything else
```

## Repository layout

| Path | What it is |
|---|---|
| `backend/packages/` | `agnostic-kernel` (settings, db, jobs, modules, auth), `agnostic-agentos-client`, `agnostic-cel`, `agnostic-codegen`, `agnostic-spec` |
| `backend/modules/` | one uv package per feature module (`identity`, `org`, `access`, `instances`, `gateway`, `audit`, `studio`, `sources`, `assistant`, …) |
| `backend/apps/agnostic-server/` | composition root: the `agnostic` CLI, API and worker |
| `frontend/` | Yarn workspaces: `apps/web` shell, `packages/*` (`ui`, `core`, `api`, `testing`, `assistant`, `editor`, `studio`), feature modules in `modules/*` |
| `runtime/` | `agnostic-runtime`, the reference AgentOS app (contract tests, demos, customer template) |
| `bridge/` | `agnostic-bridge`, the optional package customers install in their AgentOS |
| `deploy/` | `dev/` (development Compose, never shipped), `compose/`, `helm/` |
| `scripts/` | dev seed, fixture recording, license checks, upgrade and restore drills |
| `docs/` | architecture, how-to guides, reference: [start here](docs/README.md) |

## License

BSD 3-Clause, see [LICENSE](LICENSE).
