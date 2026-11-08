# AgentOS runtime and client

## `agnostic-runtime` (reference AgentOS)

`runtime/` is a small AgentOS app on agno 3.1.12 (Python 3.13): the contract-test target, a demo, and a template
for customers. It isn't shipped with Agnostic. `just runtimes` starts two ([guide](../how-to/reference-runtimes.md)).

- Sync `PostgresDb` (Studio needs one) with pgvector; tracing, scheduler and a durable Redis queue on; telemetry off.
- `app/registry.py`: tools, mock model presets (`mock-precise`, `mock-creative`), schemas, the `support-memory`
  memory manager, step functions (`app/functions.py`).
- `user_isolation` on for `dev-prod`, else `RUNTIME_USER_ISOLATION`; JWT `Authorization(verify_audience=True, …)`
  when `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` is set, else no auth.
- Components, one file each: agents `support-triage`, `billing-agent`, `kb-researcher`, `qa-reviewer`,
  `web-researcher`, `summarizer`; teams `research-team`, `escalation-team`, `onboarding-team`; workflows
  `ticket-router`, `daily-brief`, `refund-review`. `refund_customer` is an `@approval` tool.
- `app/models/mock.py` is deterministic: the same input gives the same answer, a message naming a tool calls it with
  parsed arguments (`refund 19.99 to cus_42`), and streaming yields the text word by word. Two longer runs are
  scripted in `app/models/scenarios.py` for demos and screenshots: ask the Pi or OpenCode coder to *fix* a bug and
  it reproduces it with a test, edits the code and re-runs the tests in its sandbox; ask `web-researcher` to
  *research* or *compare* pgvector indexes and it searches three times, then answers with sources.
- `app = install(agent_os)` installs the bridge.

## `agnostic-bridge`

`bridge/` is an optional package customers add to their AgentOS (built from this repository into their image, not
published to an index; Python ≥ 3.10,
`agno[os]>=3.1.12,<3.2`). `install(agent_os)` adds routes under `/agnostic/v1`, mounted ahead of AgentOS's MCP
catch-all and protected by AgentOS's own auth (their scopes go into `app.state.scope_mappings`). It keeps no state.

| Route | Scopes | Returns |
|---|---|---|
| `GET /capabilities` | `config:read` | versions, `os_id`, replica id, enabled features, endpoints |
| `POST /evals/run` | `evals:write` | an eval run against a chosen config version, drafts included |
| `GET /files/provenance` | `filesystem:read`, `traces:read` | file-tool calls on a path, from stored traces |
| `GET /workers` | `agent_os:admin` | this replica's queue and scheduler |
| `GET /events` | `approvals:read`, `schedules:read` | new approvals and failed schedule runs since a time |
| `POST /components/validate`, `/normalize` | `components:read` | strict `from_dict` errors; lenient `from_dict` → `to_dict()` |
| `GET /introspect/components` | `components:read` | code-defined components with module, file, line, config |
| `POST /cel/evaluate` | `components:read` | agno's evaluation of a CEL expression (503 without `agno[cel]`) |
| `GET /registry/{type}/{name}/source` | `registry:read` | where a registry entry is defined, `declared`, approval flags |

Component routes need a sync db. The control plane marks the bridge available on a `2xx` from `/capabilities`.
`direct_mode_cors(origins)` is the CORS config for [direct mode](identity-access-gateway.md#the-gateway).

`app/dump_golden.py` (`just golden`) writes `to_dict()` of every runtime component to `backend/tests/golden/agno-3.1/`;
`contract.yml` regenerates them and fails on a diff, so agno serialization changes are reviewed with the upgrade.

## `agnostic-agentos-client`

`backend/packages/agnostic-agentos-client`: the typed async client for every AgentOS. It doesn't depend on agno (only
the `assistant` module does).

- **Transport**: httpx, HTTP/2, one pool per instance; idempotent GETs retry on connection errors and 502/503/504.
- **Auth**: `NoAuth`, `SecurityKeyAuth`, `StaticBearerAuth`, `BearerAuth(token_provider)`.
- **Errors**: `InstanceUnreachableError`, `InstanceAuthFailedError` (401), `ForbiddenError` (403), `NotFoundError`
  (404), `CapabilityDisabledError` (503), `UnexpectedResponseError`.
- **Models**: generated from `openapi/agentos-3.1.12.json` (`just agentos-client-gen`); `OsConfig` types the `/config`
  sections the control plane uses and keeps the rest.
- **Methods**: `health()`, `info()`, `config()`; `get_json()` / `request_json()` for other routes (mapped errors,
  only GETs retried); `probe()` → `(status, body excerpt)` without mapping; `open_stream()` → the unread response for
  the gateway passthrough (no mapping, no retries).

## Contract tests

`backend/tests/contract/` runs against a live runtime (`just test-contract`; CI `contract.yml` on changes and
nightly): `test_agentos_runtime.py`, `test_inline_approvals.py`, `test_studio_configs.py`. To upgrade agno: bump
`runtime/pyproject.toml`, `uv lock`, `just agentos-client-gen`, review the model diff, run the suite. Renovate holds
agno upgrades for approval.
