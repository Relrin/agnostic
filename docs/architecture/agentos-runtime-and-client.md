# AgentOS runtime and client

## `agnostic-runtime` (reference AgentOS)

`runtime/` is a small AgentOS app on agno 3.1.12 (Python 3.13, agno's supported range). It serves three purposes:
a target for our contract tests, a demo with the prototype's sample domain, and a template for customers who
don't run AgentOS yet. It's never shipped with Agnostic.

It follows the recommended production recipe:

| Setting | Value |
|---|---|
| database | sync `PostgresDb` (Studio needs a sync db) in its own database, with pgvector available |
| `tracing` | on |
| `scheduler` | on, with a shared `internal_service_token` |
| `queue` | `QueueConfig(durable=True, redis=…)` |
| `registry` | `app/registry.py`: tools, mock model presets (ids `mock-precise`, `mock-creative`), the `TriageResult` and `RefundRequest` schemas (`app/schemas.py`), the `support-memory` memory manager, the database |
| `user_isolation` | on for `dev-prod`; elsewhere `RUNTIME_USER_ISOLATION` (default off) |
| `authorization` | `Authorization(verify_audience=True, audience=<runtime id>, issuer=RUNTIME_JWT_ISSUER)` when `JWT_VERIFICATION_KEY` (or `JWT_JWKS_FILE`) is set; otherwise `auth_mode=none` for development |
| `telemetry` | off |
| bridge | `agnostic-bridge` installed (`app = install(agent_os)`): every route in [the bridge table](#agnostic-bridge) |

Sample components (one file each, matching the Sources path mapping):

- agents: `support-triage`, `billing-agent`, `kb-researcher`, `qa-reviewer`, `web-researcher`, `summarizer`
  (`app/agents/`);
- teams: `research-team` (coordinate), `escalation-team` (route) (`app/teams/`);
- workflows: `ticket-router` (triage, then a CEL `Router`), `daily-brief` (`app/workflows/`).

`refund_customer` is decorated with `@approval`: a run that calls it pauses (`PAUSED`) and an approval appears in
`/approvals`.

### The mock model

`app/models/mock.py` is a deterministic model, so tests and demos never call an LLM:

- the same input always gives the same answer, prefixed with the agent's persona;
- if the user message names a tool the agent has (`refund`, `order`, `search`, `web`), it calls it with
  arguments parsed from the message (`refund 19.99 to cus_42` → `{"customer_id": "cus_42", "amount": 19.99}`);
- after a tool result it replies `Done. <result>`;
- streaming yields the same text word by word.

Run two instances with `just runtimes` ([guide](../how-to/reference-runtimes.md)).

## `agnostic-bridge`

`bridge/` is the optional companion customers add to their own AgentOS (`pip install agnostic-bridge`; Python
3.10-3.13, agno 3.1.x). `install(agent_os)` returns `agent_os.get_app()` with routes under `/agnostic/v1`:

- placed ahead of the first mount, so AgentOS's MCP catch-all (`mcp=True` mounts its app at `/`) never shadows them;
- protected by AgentOS's own auth layer: their scopes are added to `app.state.scope_mappings`, the route → scopes
  table AgentOS's auth middleware reads, so JWTs, service-account tokens and `agent_os:admin` behave as on built-in
  routes;
- stateless: the bridge keeps nothing of its own; only the eval route calls models, and it stores its result in
  the AgentOS db.

| Route | Scopes | What it does |
|---|---|---|
| `GET /agnostic/v1/capabilities` | `config:read` | Bridge, agno and Python versions, `os_id`, a replica id (`AGNOSTIC_BRIDGE_REPLICA_ID`, else `<hostname>:<pid>`), the features the AgentOS object runs and the bridge's endpoints |
| `POST /agnostic/v1/evals/run` | `evals:write` | `POST /eval-runs` against a chosen config version of an agent or team, drafts included |
| `GET /agnostic/v1/files/provenance` | `filesystem:read`, `traces:read` | File-tool calls on one workspace path, from the stored traces |
| `GET /agnostic/v1/workers` | `agent_os:admin` | The answering replica's queue and scheduler |
| `GET /agnostic/v1/events` | `approvals:read`, `schedules:read` | New approvals and failed schedule runs since a point in time |
| `POST /agnostic/v1/components/validate` | `components:read` | `{kind, config}` → `{valid, errors: [{path, message}]}`: a strict `from_dict` against the registry and db |
| `POST /agnostic/v1/components/normalize` | `components:read` | `{kind, config}` → `{config}`: a lenient `from_dict`, then `to_dict()`; 422 with `{valid, errors}` when it can't be built |
| `GET /agnostic/v1/introspect/components` | `components:read` | Code-defined agents, teams and workflows: `[{id, kind, name, module, file, line, config}]` |
| `GET /agnostic/v1/registry/{type}/{name}/source` | `registry:read` | `{type, name, module, file, line, declared, requires_confirmation, approval_type}` for one registry entry; 404 when it isn't registered |

The component routes need a synchronous db (503 otherwise) and store nothing. Source locations are best-effort and
null when `inspect` can't find them. The control plane's capability probe marks the bridge available on a `2xx` from
`/capabilities`. `app.dump_openapi` leaves the bridge's paths out of the pinned AgentOS OpenAPI snapshot.

### Golden configs

`app/dump_golden.py` (`just golden`) writes `to_dict()` of every runtime agent and team, plus two fixtures that set
every field Studio edits, to `backend/tests/golden/agno-3.1/{agents,teams}/<id>.json`. `contract.yml` regenerates
them and fails when they differ from the committed files, so a change in how agno serializes a config is reviewed
with the agno upgrade.

## `agnostic-agentos-client`

`backend/packages/agnostic-agentos-client` is the typed async client the control plane uses for every AgentOS.

- **Transport**: httpx with HTTP/2 and one pool per instance; idempotent GETs retry on connection errors and
  502/503/504 with exponential backoff.
- **Auth**: `NoAuth`, `SecurityKeyAuth` (`OS_SECURITY_KEY`), or `BearerAuth(token_provider)` for minted JWTs.
- **Errors**: `InstanceUnreachableError`, `InstanceAuthFailedError` (401), `ForbiddenError` (403),
  `NotFoundError` (404), `CapabilityDisabledError` (503: feature not enabled on that runtime),
  `UnexpectedResponseError` (anything else, or a body that doesn't match the pinned schema).
- **Models**: generated with datamodel-code-generator from `openapi/agentos-3.1.12.json`, the OpenAPI document of
  the pinned runtime (`_generated/models.py`). AgentOS publishes `/config` as a free-form object, so `OsConfig`
  types the sections the control plane relies on and keeps the rest as extra fields.
- **Methods (v0)**: `health()`, `info()`, `config()`. Later phases add one method per endpoint they need.

We don't reuse agno's own client in the control plane: it would pull agno into the Python 3.15 process.

## Contract tests

`backend/tests/contract/` checks the client and its models against a live runtime: `/health`, `/info` (agno
version equals the pinned one, component counts) and `/config` (the sample components, queue and tracing
sections). Run them with `just test-contract`; CI runs them in `contract.yml` on changes and nightly.

Upgrading agno: bump it in `runtime/pyproject.toml`, `uv lock`, run `just agentos-client-gen`, review the model
diff, run the contract suite. Renovate holds agno upgrades for approval for this reason.
