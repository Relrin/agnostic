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
| [Context](architecture/context.md) | memory duplicates, provenance and optimization, knowledge content and retrieval, learnings and data deletion, file provenance |
| [Observe and evaluations](architecture/observe-and-evals.md) | trace comparison, span statistics, metrics and cost estimates, eval datasets, batches, version comparison, publish gates |
| [Studio](architecture/studio.md) | typed configs and code generation, the registry and used-by index, drafts and autosave, validation, gated publish with overrides, draft test runs, teams, promotion, golden fixtures |
| [Control](architecture/control.md) | approvals inbox, routing and expiry, notifications (inbox, Slack, email, webhooks), scheduler previews, the durable queue and checkpoint recovery |
| [Access governance](architecture/access-governance.md) | groups and IdP sync (SCIM, claims, Google), editable roles, service accounts, temporary access, SAML and MFA, audit views, export, SIEM, archive |

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
| [Sign-in providers](how-to/sign-in-providers.md) | local accounts, GitHub, GitLab, Google, Okta, any OIDC or SAML provider, enforcing SSO, MFA |
| [Okta](how-to/idp/okta.md), [Entra ID](how-to/idp/entra-id.md), [Keycloak](how-to/idp/keycloak.md), [Google Workspace](how-to/idp/google-workspace.md) | SSO with each identity provider, SCIM provisioning, group sync |
| [SIEM streaming and the audit archive](how-to/audit-siem-and-archive.md) | webhook, syslog and OTLP destinations, retention, the S3 archive, restore, the hash chain |
| [Testing](how-to/testing.md) | unit, integration, contract, Storybook a11y, Playwright |
| [Dependencies](how-to/dependencies.md) | exact pinning, upgrades, Renovate, license policy |
| [Troubleshooting](how-to/troubleshooting.md) | Windows, ports, Docker, common errors |

## Reference

- [CLI](reference/cli.md): every `agnostic` command.
- [Configuration](reference/configuration.md): every setting and its environment variable.
- [API conventions](reference/api-conventions.md): errors (problem+json), ids, pagination, request ids.

## Decisions

[Architecture decision records](adr/README.md): the decisions this code depends on, with context and consequences.
