# Module system

The control plane is a modular monolith: features are **modules**, separate distributions that plug into the
kernel through one contract (`backend/packages/agnostic-kernel/src/agnostic_kernel/modules.py`). Customers can add
modules as wheels; operators can turn modules off.

## The contract

A module registers one object in the `agnostic.modules` entry-point group:

```toml
# modules/audit/pyproject.toml
[project.entry-points."agnostic.modules"]
audit = "agnostic_audit.module:AuditModule"
```

It implements `Module`; subclass `BaseModule` and override only what you contribute:

| Member | Contributes |
|---|---|
| `name`, `version`, `depends_on` | identity and the modules it needs |
| `settings_model()` | a `BaseSettings` class for `AGNOSTIC_<NAME>__*` |
| `provide()` | dishka providers (repositories, use cases, the facade) |
| `routers()` | `RouterSpec(router, prefix, tags)` mounted under `/api/v1`; `root=True` mounts at the root (SCIM, git webhooks) |
| `metadata()`, `migrations()` | SQLAlchemy metadata and the Alembic version directory |
| `scopes()` | control-plane scopes it defines (`audit:read`) |
| `jobs()`, `event_handlers()` | `JobSpec`s (tasks and periodic schedules); `EventHandlerSpec`s for domain events |
| `audit_actions()` | audit vocabulary and summary templates |
| `search_providers()`, `capabilities()` | command-palette documents; AgentOS capability probes |
| `assistant_tools()` | read-only `ToolSpec`s the assistant runs as the asking person |
| `sealed_columns()` | `SealedColumn`s holding `SecretBox` values, re-sealed by `agnostic secrets rotate` |
| `features()` | features switched on right now, merged into `GET /api/v1/system/features` |
| `endpoint_checks()` | probes of the endpoints it calls (IdPs, instances, archive storage) for `config check --connect` and the System page |
| `system_status()` | health of its background work (delivery backlogs, sync errors) for the System page |
| `on_startup()`, `on_shutdown()` | lifecycle hooks with the app container |

`GET /api/v1/system/modules` and `agnostic modules list` show what each enabled module contributes.

## Loading

`load_modules()` discovers entry points, drops modules named in `AGNOSTIC_MODULES__DISABLED`, and orders the rest
by `depends_on`. Start-up fails, with a sentence saying what to do, on a module installed twice, a missing
dependency, a cycle, a dependency on a disabled module, or an unknown name in the disabled list.

Disabling a module removes its routes, jobs and providers. Its tables stay: migrations cover every *installed*
module, so turning one off never strands its revisions.

## Inside a module

Hexagonal layout (`agnostic_audit/` as the example): `module.py`, `settings.py`, `domain/` (entities and rules,
standard library only), `application/` (use cases and ports), `infrastructure/` (tables, repositories, adapters),
`api/` (router, schemas, assistant tools), `jobs.py`, `facade.py` (the only import surface for other modules),
`providers.py` (dishka wiring), `migrations/versions/` (one revision per module).

![Module layers: api, application, domain, infrastructure, facade, providers and jobs, and the import-linter contracts](images/module-layers.svg)

## Boundaries

import-linter contracts in `backend/pyproject.toml`, checked by `lint-imports` in CI:

- packages (`agnostic_kernel`, `agnostic_agentos_client`, `agnostic_spec`, `agnostic_cel`, `agnostic_codegen`) never
  import modules or the server;
- modules never import the server;
- within a module: `module` → `providers | jobs` → `api | infrastructure` → `settings` → `facade` → `application` →
  `domain`;
- a module's `domain` imports only the standard library;
- other modules import only a module's `facade`;
- only `assistant` imports agno.

The per-module contracts follow one shape; when you add a module, add its contracts to `[tool.importlinter]`.

## Talking across modules

Modules import each other's `facade` only, along `depends_on`:

| Layer | Modules |
|---|---|
| 1 | `audit` |
| 2 | `settings`, `identity`, `instances` |
| 3 | `org`, `search`, `system` |
| 4 | `directory` |
| 5 | `access` |
| 6 | `gateway`, `service_accounts`, `notifications` |
| 7 | `context`, `evals`, `observe`, `queue`, `assistant` |
| 8 | `approvals`, `scheduler`, `studio` |
| 9 | `sources` |

![Module dependencies: the `depends_on` graph of every backend module](images/module-dependencies.svg)

When a call must point the other way, the lower module declares a port and the higher one provides it through
dishka:

| Port | Declared by | Provided by | Why |
|---|---|---|---|
| `PrincipalResolver` | kernel | identity | routes take `FromDishka[Principal]` without knowing about sessions |
| `Authorizer` | kernel | access | every module calls `authorizer.require(principal, scope, instance_id=…)` |
| `Bootstrapper` | kernel | org | `agnostic bootstrap` |
| `MembershipDirectory` | identity | org | sign-in asks whether an account belongs to the org |
| `ExternalGroupsSync` | identity | directory | IdP group claims at sign-in |
| `BearerPrincipalResolver` | identity | service_accounts | gateway tokens as principals |
| `InitialBindingsApplier` | org | access | invitations carry role bindings, granted on acceptance |
| `GroupDirectory` | org | directory | invitations and member actions add people to groups |
| `AccessRevoker` | directory | access | deprovisioning removes bindings |
| `PublishHold` | studio | sources | publishing waits for a pull request to merge |

Modules that may not depend on each other announce facts with `DomainEvents` instead (see
[control](control.md#domain-events)).

## Frontend modules

The web app has the same idea: a module is a workspace package exporting a `defineModule()` manifest. See
[frontend](frontend.md#module-sdk) and [add a frontend module](../how-to/add-frontend-module.md).
