# Module system

The control plane is a modular monolith: features are **modules**,
separate distributions that plug into the kernel through one contract. Customers can add modules as wheels and
operators can turn modules off.

## The contract

A module registers one object in the `agnostic.modules` entry-point group:

```toml
# modules/audit/pyproject.toml
[project.entry-points."agnostic.modules"]
audit = "agnostic_audit.module:AuditModule"
```

It implements `agnostic_kernel.modules.Module`; subclass `BaseModule` and override only what you contribute:

| Member | Contributes |
|---|---|
| `name`, `version`, `depends_on` | identity and the modules it needs |
| `settings_model()` | a `BaseSettings` class for `AGNOSTIC_<NAME>__*` |
| `provide()` | dishka providers (repositories, use cases, the facade) |
| `routers()` | `RouterSpec(router, prefix, tags)` mounted under `/api/v1` |
| `metadata()`, `migrations()` | the module's SQLAlchemy metadata and Alembic version directory |
| `scopes()` | control-plane scopes it defines (`audit:read`) |
| `jobs()` | `JobSpec`s: background tasks and periodic schedules |
| `event_handlers()` | domain-event subscriptions |
| `audit_actions()` | audit vocabulary and summary templates |
| `search_providers()`, `capabilities()` | command-palette search and AgentOS capability probes (later phases) |
| `on_startup()`, `on_shutdown()` | lifecycle hooks with the app container |

`GET /api/v1/system/modules` and `agnostic modules list` show what each enabled module contributes.

## Loading

`load_modules()` discovers entry points, drops modules named in `AGNOSTIC_MODULES__DISABLED`, and orders the rest
by `depends_on`. It fails at start-up, with a sentence that says what to do, when:

- a module is installed twice;
- a dependency isn't installed;
- the dependencies form a cycle;
- a module depends on a disabled module (disable it too);
- the disabled list names an unknown module.

Disabling a module removes its routes, jobs and providers. Its tables stay: migrations always cover every
*installed* module, so turning a module off never strands its revisions.

## Inside a module

Hexagonal layout, using `audit` as the example:

```
agnostic_audit/
  module.py            the Module implementation
  settings.py          AGNOSTIC_AUDIT__* settings
  domain/              entities and rules; standard library only
  application/         use cases and ports (Protocols)
  infrastructure/      SQLAlchemy tables and repositories, adapters to kernel services
  api/                 FastAPI router and Pydantic schemas
  jobs.py              background jobs
  facade.py            the only import surface for other modules
  providers.py         dishka wiring
  migrations/versions/ the module's Alembic branch
```

## Boundaries

import-linter contracts in `backend/pyproject.toml`, checked by `lint-imports` in CI:

- packages (`agnostic_kernel`, `agnostic_agentos_client`) never import modules or the server;
- modules never import the server;
- within a module: `module` → `providers | jobs` → `api | infrastructure` → `facade` → `application` → `domain`;
- a module's `domain` imports only the standard library.

- other modules import only a module's `facade` (one generated contract per module).

The contracts are generated for every module; when you add one, add it to the list in the
`[tool.importlinter]` section (same shape as the others).

## Talking across modules

Modules depend on each other through `depends_on` and import each other's `facade` only. When the dependency would
point the wrong way, the lower module declares a port in its facade and the higher module provides it through
dishka:

| Port | Declared by | Provided by | Why |
|---|---|---|---|
| `PrincipalResolver` | kernel | identity | routes depend on `FromDishka[Principal]` without knowing about sessions |
| `Authorizer` | kernel | access | every module calls `authorizer.require(principal, scope, instance_id=…)` |
| `MembershipDirectory` | identity | org | sign-in asks whether an account belongs to the org; SSO newcomers join through invitations or JIT |
| `InitialBindingsApplier` | org | access | invitations carry role bindings, granted on acceptance |
| `Bootstrapper` | kernel | org | `agnostic bootstrap` in the composition root |
| `PublishHold` | studio | sources | publishing waits until a pull request carrying the version merged, for sources that ask for it |

P01 modules and their order: `audit` → `settings`, `identity`, `instances` → `org` → `access` → `gateway`
(see [identity, access and the gateway](identity-access-gateway.md)).

## Frontend modules

The web app has the same idea: a module is a workspace package exporting a `defineModule()` manifest. See
[frontend](frontend.md#module-sdk) and [add a frontend module](../how-to/add-frontend-module.md).
