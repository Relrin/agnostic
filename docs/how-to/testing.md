# Testing

| Layer | Where | Run | Needs |
|---|---|---|---|
| Backend unit + API | `backend/tests/unit`, `backend/tests/api` | `just test` | nothing (SQLite, in-process jobs) |
| Backend integration | `backend/tests/integration` (`-m integration`) | `just test-int` | Docker, or the dev stack |
| Contract | `backend/tests/contract` (`-m contract`) | `just test-contract` | a running reference runtime |
| Assistant Q&A | `-m assistant_eval` | `just test-assistant` | a model (default: the dev Ollama, `just ai-up`) |
| Runtime, bridge | `runtime/tests`, `bridge/tests` | `just test` | nothing |
| Frontend unit | `**/src/**/*.test.ts(x)` | `just test` | nothing (jsdom, MSW) |
| Storybook a11y | every story | `yarn workspace @agnostic/ui storybook:test` | Playwright Chromium |
| E2E | `frontend/apps/web/e2e` | `yarn e2e` | Playwright Chromium |

`just test-ui` runs the last two. Install the browser once:
`cd frontend && yarn workspace @agnostic/web playwright install chromium`.

## Backend

- Unit and API tests build the real app with `make_settings(sqlite_url(tmp_path))` and drive it through
  `httpx.ASGITransport` + `asgi-lifespan`, so routes, DI, migrations and jobs all run.
- Integration tests get PostgreSQL and Redis from testcontainers, or from your dev stack:

  ```bash
  AGNOSTIC_TEST_DATABASE_URL=postgresql://agnostic:agnostic@localhost:5432/agnostic \
  AGNOSTIC_TEST_REDIS_URL=redis://localhost:6379/0 just test-int
  ```

  Each test that needs a database gets a fresh one (`fresh_postgres`), dropped afterwards.
- Schema guards: `tests/unit/test_migrations_schema.py` (SQLite) and `test_migrations_match_models_on_postgres` in
  `tests/integration/test_postgres_redis.py` compare the migrated schema with the models
  ([migrations](migrations.md#guard-tests)).
- Domain and kernel suites: `tests/unit/test_identity_org_instances_domain.py`, `test_operate_domain.py`,
  `test_kernel_mail_and_store.py`; PostgreSQL paths in `tests/integration/test_sessions_gateway_audit_postgres.py`
  and `test_realtime_search_postgres.py`.
- Cache compatibility (manual; CI tests Redis only): `AGNOSTIC_TEST_REDIS_IMAGE=valkey/valkey:9.1.3-alpine just test-int`.
- Coverage: the kernel stays at 90 % or more (`--cov-fail-under=90` in `just test` and CI).

## Contract tests and recorded fixtures

`tests/contract/test_inline_approvals.py` talks to the runtime without a token: point it at a runtime started
without `JWT_VERIFICATION_KEY` (`auth_mode=none`). The same runtime records the RunStream fixtures:

```bash
cd backend && uv run python ../scripts/record_sse_fixtures.py --url http://127.0.0.1:7777
```

This rewrites `frontend/packages/core/src/run-stream/__fixtures__/recorded/`, which `recorded.test.ts` folds through
the reducer.

Studio's golden fixtures live in `backend/tests/golden/agno-3.1`: agno's `to_dict()` of the reference runtime's
agents, teams and workflows, plus a ticket router in `prototype/`, as `.json`, each with the code Studio generates
for it (`.py`). After an agno upgrade or a generator change, run `just golden` and review the diff; the contract job
fails when the runtime serializes differently from the committed JSON.

## Frontend

- Render pages with `renderPage(Page, { path, url })` from `@agnostic/testing` (a minimal router, so params and
  search params work) or components with `renderWithProviders()`. Mock the API with MSW: `sampleOrgHandlers()`
  (`packages/testing/src/sample-org.tsx`) serves the sample org (Localhost Company, Daniel, Marcus,
  `prod-agentos`, `staging-agentos`) for `/me`, `/org`, `/instances`, access and audit; `operateHandlers()`
  (`operate.tsx`) adds Home's overview, approvals, search and the gateway's agents, teams, workflows and sessions. Unhandled requests fail the test.
- Workflow builder: `workflowHandlers()` serves a stored ticket-router workflow with validation, CEL, stats, runs
  and the canvas layout. React Flow and CodeMirror need the jsdom layout stubs in `builder-page.test.tsx`; click
  canvas nodes with `fireEvent` (a pointer press starts React Flow's drag).
- Every story is rendered in Chromium and checked with axe (WCAG 2.2 AA); a violation fails the run.
- Playwright runs Chromium with its sandbox on (`launchOptions.chromiumSandbox`); `studio-workflows.spec.ts` also
  checks that a 200-step workflow pans and zooms within the frame budget.
- `packages/ui/src/lib/tokens.test.ts` checks text/background contrast and that the token mirror matches
  `tokens.css`.

## Visual baselines

`e2e/shell.spec.ts` compares the sidebar with a committed screenshot (`@visual`). Font rendering differs by OS, so
baselines are per platform (`sidebar-chromium-win32.png`, `-linux.png`, …). Only the Windows baseline is committed,
so CI (Linux) runs `yarn e2e --grep-invert @visual`. To record the Linux one, run Playwright in its Linux image:

```bash
docker run --rm -v "$PWD/frontend:/work" -w /work/apps/web mcr.microsoft.com/playwright:v1.64.1-noble \
  sh -c "corepack enable && yarn install --immutable && yarn e2e --grep @visual --update-snapshots"
```

then commit `e2e/shell.spec.ts-snapshots/sidebar-chromium-linux.png` and drop `--grep-invert @visual` from
`.github/workflows/ci.yml`.
