# Agnostic documentation

## Start here

- [Getting started](getting-started.md): run the stack, find your way around, make a first change.
- [Architecture overview](architecture/overview.md): what runs where and why.

## Architecture

| Page | Covers |
|---|---|
| [Overview](architecture/overview.md) | containers, data ownership, gateway, repository layout |
| [Backend kernel](architecture/backend-kernel.md) | settings, logging, tracing, database, cache, jobs, errors, ids, pagination, health |
| [Module system](architecture/module-system.md) | the `Module` contract, discovery, ordering, disabling, boundaries |
| [Frontend](architecture/frontend.md) | shell, module SDK, routing, data layer, design tokens and primitives |
| [AgentOS runtime and client](architecture/agentos-runtime-and-client.md) | `agnostic-runtime`, the mock model, `agnostic-agentos-client`, contract tests |
| [Identity, access and the gateway](architecture/identity-access-gateway.md) | sign-in, sessions, org roles, bindings, effective scopes, instances and keys, the gateway pipeline, audit |
| [Operate and realtime](architecture/operate-and-realtime.md) | RunStream, approvals and delegated elevation, Home overview, realtime events, ⌘K search |

## How-to guides

| Guide | Task |
|---|---|
| [Add a backend module](how-to/add-backend-module.md) | a new bounded context with routes, tables, jobs |
| [Add a frontend module](how-to/add-frontend-module.md) | a new page in the shell, its nav entry and commands |
| [Write migrations](how-to/migrations.md) | Alembic branches per module, upgrade/downgrade |
| [Background jobs](how-to/background-jobs.md) | Procrastinate tasks, periodic jobs, progress |
| [Configuration and endpoints](how-to/configuration.md) | env vars, TOML, TLS, PostgreSQL vs SQLite |
| [Regenerate API clients](how-to/api-clients.md) | OpenAPI → TypeScript, AgentOS OpenAPI → Python models |
| [Run the reference runtimes](how-to/reference-runtimes.md) | two AgentOS instances for development, JWT trust, `just seed`, the bridge |
| [Sign-in providers](how-to/sign-in-providers.md) | local accounts, GitHub, GitLab, Google, Okta, any OIDC provider |
| [Testing](how-to/testing.md) | unit, integration, contract, Storybook a11y, Playwright |
| [Dependencies](how-to/dependencies.md) | exact pinning, upgrades, Renovate, license policy |
| [Troubleshooting](how-to/troubleshooting.md) | Windows, ports, Docker, common errors |

## Reference

- [CLI](reference/cli.md): every `agnostic` command.
- [Configuration](reference/configuration.md): every setting and its environment variable.
- [API conventions](reference/api-conventions.md): errors (problem+json), ids, pagination, request ids.

## Decisions

[Architecture decision records](adr/README.md): the decisions this code depends on, with context and consequences.
