# Contributing

The workflow for changes; the [docs](docs/README.md) explain the code.

## Set up

Follow the [README](README.md#quick-start), then install the git hooks:

```bash
just hooks
```

On commit the hooks run ruff, basedpyright, ESLint, Prettier, gitleaks and file hygiene checks; on the commit message,
a Conventional Commits check.

## Branches and commits

- Trunk-based: short-lived branches off `master`, merged by pull request.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat(kernel): …`, `fix(web): …`, `docs: …`,
  `chore(deps): …`. Scopes are package or module names (`kernel`, `server`, `identity`, `gateway`, `ui`, `core`, `api`,
  `runtime`, `bridge`, `client`, `ci`).

## Before you open a pull request

```bash
just check      # lint, types, unit + integration tests, API client drift, licenses
just test-ui    # if you touched the frontend
```

CI runs the same gates, plus the contract suite when the runtime or the AgentOS client changes.

## Rules the checks enforce

- **Exact versions.** Every dependency, tool, image and GitHub Action is pinned exactly; lockfiles are committed.
  See [dependencies](docs/how-to/dependencies.md).
- **Strict types.** basedpyright `strict`; TypeScript `strict` with `noUncheckedIndexedAccess` and
  `exactOptionalPropertyTypes`.
- **Boundaries.** Backend: import-linter contracts (packages never import modules; a module's domain is pure).
  Frontend: modules never import each other; only `@agnostic/ui` touches Radix.
- **Generated code is generated.** Don't edit `frontend/packages/api/src/generated`, `docs/reference/api.md` or
  `agnostic_agentos_client/_generated`; run `just api-gen` or `just agentos-client-gen`.
- **Migrations match the models.** `tests/unit/test_migrations_schema.py` fails when the migrated schema and the
  table models differ ([migrations](docs/how-to/migrations.md)).
- **Licenses.** New dependencies must pass `just licenses`; weak copyleft needs a reviewer and an entry in the
  license scripts' allowlist.
- **Accessibility.** Stories must pass axe (WCAG 2.2 AA).

## Adding things

- A backend module: [how-to](docs/how-to/add-backend-module.md).
- A frontend module: [how-to](docs/how-to/add-frontend-module.md).
- A migration or a background job: [migrations](docs/how-to/migrations.md), [jobs](docs/how-to/background-jobs.md).
