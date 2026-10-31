# Agnostic

A self-hosted control plane for [Agno](https://github.com/agno-agi/agno) AgentOS runtimes: identity and access,
instance management, operations, observability and a Studio for agents, teams and workflows. It runs entirely
inside your network and talks to every AgentOS over its REST/SSE API.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | 0.13.6 | installs Python 3.15.2 (control plane) and 3.13 (reference runtime) for you |
| Node.js | 26.13.0 (Active LTS; `.nvmrc`) | 24.11+ works for local development |
| Yarn | 4.18.1 | bundled in `frontend/.yarn/releases`; any global `yarn` delegates to it |
| Docker | with Compose v2 | for PostgreSQL and Redis; optional if you use SQLite |
| [just](https://just.systems) | 1.59.0 | `uv tool install rust-just==1.59.0` |
| Git | any | on Windows, Git for Windows provides the `sh` that `just` uses |

## Build and run from scratch

```bash
git clone <this repository> agnostic && cd agnostic
just setup      # .env from .env.example, uv sync (backend + runtime), yarn install — all from lockfiles
just up         # PostgreSQL 18 (+pgvector) and Redis 8 in Docker
just migrate    # agnostic schema, Procrastinate tables, module tables
just dev        # API + worker on :8000, web app on :5173
```

Open <http://localhost:5173>. The shell opens on the `dev-prod` instance; the **Hello** page writes a greeting,
a background job replies to it.

No Docker? Set `AGNOSTIC_DATABASE__URL=sqlite:///agnostic.db` in `.env`, then `just migrate && just dev`. Jobs run
inside the API process in that mode (see [configuration](docs/how-to/configuration.md)).

Optional: `just runtimes` starts two reference AgentOS instances (`dev-prod` on :7777, `dev-staging` on :7778)
with the prototype's sample agents, and `just test-contract` checks the typed client against them.

## Checks

```bash
just check      # lint, types, unit + integration tests, API client drift, licenses
just test-ui    # Storybook a11y tests and Playwright e2e
just --list     # everything else
```

## Repository layout

| Path | What it is |
|---|---|
| `backend/` | uv workspace: `agnostic-kernel`, `agnostic-agentos-client`, the `hello` module, the `agnostic` server and CLI |
| `frontend/` | Yarn workspaces: `apps/web` shell, `@agnostic/ui`, `@agnostic/core`, `@agnostic/api`, `modules/hello` |
| `runtime/` | `agnostic-runtime`, the reference AgentOS app (contract tests, demos, customer template) |
| `deploy/dev/` | Docker Compose for development dependencies (never shipped) |
| `docs/` | architecture, how-to guides, reference - [start here](docs/README.md) |

## License

BSD 3-Clause, see [LICENSE](LICENSE).
