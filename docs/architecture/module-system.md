# Module system

The control plane is a modular monolith: features are **modules**,
separate distributions that plug into the kernel through one contract. Customers can add modules as wheels and
operators can turn modules off.

## The contract

A module registers one object in the `agnostic.modules` entry-point group:

```toml
# modules/hello/pyproject.toml
[project.entry-points."agnostic.modules"]
hello = "agnostic_hello.module:HelloModule"
```

It implements `agnostic_kernel.modules.Module`; subclass `BaseModule` and override only what you contribute:

| Member | Contributes |
|---|---|
| `name`, `version`, `depends_on` | identity and the modules it needs |
| `settings_model()` | a `BaseSettings` class for `AGNOSTIC_<NAME>__*` |
| `provide()` | dishka providers (repositories, use cases, the facade) |
| `routers()` | `RouterSpec(router, prefix, tags)` mounted under `/api/v1` |
| `metadata()`, `migrations()` | the module's SQLAlchemy metadata and Alembic version directory |
| `scopes()` | control-plane scopes it defines (`hello:read`) |
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

Hexagonal layout, using `hello` as the example:

```
agnostic_hello/
  module.py            the Module implementation
  settings.py          AGNOSTIC_HELLO__* settings
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

When a second module exists, add a contract that lets it import only the other module's `facade` (a commented
template is in `backend/pyproject.toml`).

## Frontend modules

The web app has the same idea: a module is a workspace package exporting a `defineModule()` manifest. See
[frontend](frontend.md#module-sdk) and [add a frontend module](../how-to/add-frontend-module.md).
