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
| `registry` | `app/registry.py`: tools, the mock model, the database |
| `user_isolation` | on |
| `authorization` | on when `JWT_VERIFICATION_KEY` (or `JWT_JWKS_FILE`) is set; otherwise `auth_mode=none` for development |
| `telemetry` | off |

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
