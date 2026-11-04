# Run the reference runtimes

Two development AgentOS instances from `runtime/` (`agnostic-runtime`). For your own AgentOS with the bridge in
production, see [bridge and runtime](../guides/bridge-and-runtime.md).

| Instance | URL | Database | Redis | Plays | User isolation |
|---|---|---|---|---|---|
| `dev-prod` | <http://127.0.0.1:7777> | `agentos_prod` | db 1 | production | on |
| `dev-staging` | <http://127.0.0.1:7778> | `agentos_staging` | db 2 | staging | off |

Both databases (with pgvector) are created by `deploy/dev/initdb/10-databases.sql` when the Postgres volume is
first initialised; on an older volume run `just nuke && just up`.

```bash
just up
just runtimes                     # Ctrl+C stops both
curl http://127.0.0.1:7777/info   # agno_version 3.1.12, 6 agents, 3 teams, 3 workflows
just test-contract                # against dev-prod; url=http://127.0.0.1:7778 for staging
```

Until they trust a control plane the runtimes run with `auth_mode=none`, so you can call them directly. The approval
flow:

```bash
curl -X POST http://127.0.0.1:7777/agents/billing-agent/runs \
  -F message="please refund 19.99 to cus_42" -F stream=false -F user_id=u1
# → "status": "PAUSED"
curl http://127.0.0.1:7777/approvals          # the pending refund_customer approval
```

Interactive API docs are at `/docs` on each runtime.

## Sample components

Every component runs on `MockModel` (`runtime/app/models/mock.py`): deterministic, never calls an LLM. All set
`store_events=True`, so `/resume` can replay a run from the database after AgentOS's in-memory buffer evicted it.

| Kind | Id | What it does |
|---|---|---|
| agent | `support-triage` | `lookup_order`, `search_knowledge` and `refund_customer` (`@approval`: the run pauses) |
| agent | `billing-agent` | billing questions; refunds through `refund_customer` |
| agent | `kb-researcher`, `web-researcher`, `qa-reviewer`, `summarizer` | one tool each (or none), canned answers |
| team | `research-team` | `TeamMode.coordinate` over kb-researcher, web-researcher, summarizer |
| team | `escalation-team` | `TeamMode.route` over billing-agent, qa-reviewer |
| team | `onboarding-team` | `TeamMode.tasks` over kb-researcher and summarizer: a task per member, run, completed |
| workflow | `ticket-router` | step `triage`, then a `Router` that pauses for route selection (`billing` or `research`) |
| workflow | `daily-brief` | research-team, then summarizer |
| workflow | `refund-review` | step `triage`, a `Loop` over kb-researcher (at most 2 iterations), then step `approve` with HITL |

The mock model:

- calls a tool when the latest user message names its trigger word and the tool is attached: `refund` →
  `refund_customer`, `order` → `lookup_order`, `search` → `search_knowledge`, `web` → `web_search`. After a tool
  result it answers `Done. <result>`; otherwise `[<persona>] <phrase>: <your message>`;
- takes the refund amount from the number right after `refund` (`refund 49`, `refund of $12.50`) or after `$`, else
  the first standalone number (not ids like `cus_42`), else `42`. `order 4471, refund 49 to cus_7` refunds 49 to
  `cus_7`;
- as a tasks-mode leader creates one task per member, runs them in order, then calls `mark_all_complete`
  (`TaskCreated`, `TaskUpdated` and the member runs). Coordinate and route teams answer without delegating.

Pauses you can drive from Chat (or `continue_run` in agno):

- **`support-triage` in a step**: a message with `refund` pauses `triage` on the `refund_customer` approval.
- **`ticket-router`, step `route`**: route selection with `available_choices` `billing` and `research`. agno doesn't
  evaluate the CEL selector while route selection is on; it stays in the config.
- **`refund-review`, loop `research`**: ends early once kb-researcher mentions a help-center article, otherwise after
  the second pass.
- **`refund-review`, step `approve`**: confirmation plus user input (`amount: float`, `reason: str`), then output
  review of `Refund of <amount> approved: <reason>.`

## Connect them to your control plane

The control plane signs a short-lived RS256 JWT for every call to a runtime, with a key pair per instance. A runtime
trusts the public key in `JWT_VERIFICATION_KEY` and checks each token's `aud` (its id), `iss` (the control plane's
public URL) and scopes. `just seed` runs the connect wizard for both and writes their keys:

```bash
just up && just migrate
just dev                          # terminal 1: API + web app
just runtimes                     # terminal 2: both runtimes, still auth_mode=none
just bootstrap                    # once: org "Localhost Company", Owner daniel@localhost.company
just seed                         # connects both, writes runtime/.jwt/dev-prod.pem and dev-staging.pem,
                                  # creates support-triage-studio v1-v3 (+ draft v4) on both
# restart `just runtimes`: it prints "JWT authorization on" for each key it found
just seed --test                  # Test connection for both: token accepted, scopes enforced, capabilities
```

In the web app: **Instances › Connect**, then **Settings › Connection › Test connection**.

- `just bootstrap` and `just seed` use `AGNOSTIC_DEV_OWNER_EMAIL` / `AGNOSTIC_DEV_OWNER_PASSWORD` from `.env`.
  `just seed` talks to `http://127.0.0.1:8000`; set `AGNOSTIC_DEV_API_URL` or pass `--api-url` for another address.
- It is safe to rerun: connected instances (same slug or URL) are reused, a key file is rewritten only when the active
  key changed, existing `support-triage-studio` versions are left alone. Restart the runtimes whenever it says it
  wrote a key (after a rotation, or after you reset the control-plane database).
- `support-triage-studio` is a DB component (published v1-v3, v3 current, draft v4, on the registry's
  `agnostic-mock` model) created through the gateway and AgentOS's `/components` API, for Chat's version and draft
  selectors.
- `runtime/.jwt/` is git-ignored. Delete it to put the runtimes back in `auth_mode=none`.
- `just runtimes` passes `RUNTIME_JWT_ISSUER` (from `AGNOSTIC_INSTANCES__ISSUER`, else `AGNOSTIC_HTTP__PUBLIC_URL`),
  so tokens from another control plane are rejected even with the right audience.

Once a runtime verifies JWTs, `curl` without a token gets `401` everywhere except `/health` and `/info`; go through
the gateway (`/api/v1/instances/dev-prod/os/...`) instead.

## The bridge

Both runtimes serve [`agnostic-bridge`](../../bridge) (`app = install(agent_os)` in `runtime/app/main.py`, an editable
path dependency). It mounts its routes ahead of AgentOS's MCP catch-all and registers their scopes in AgentOS's
route-scope table, so they are protected like built-in routes:

| Route (`/agnostic/v1/…`) | Scopes | For |
|---|---|---|
| `GET capabilities` | `config:read` | bridge, agno and Python versions, `os_id`, replica id, features this process runs; a `2xx` means "bridge available" |
| `POST evals/run` | `evals:write` | evals of a component version (drafts included), judged by a model that never replaces the component's |
| `GET files/provenance` | `filesystem:read`, `traces:read` | which runs wrote and read a workspace file |
| `GET workers` | `agent_os:admin` | this replica's queue worker, concurrency, in-flight jobs, `QueueConfig`, scheduler |
| `GET events?since=&limit=` | `approvals:read`, `schedules:read` | approvals created and scheduled runs failed since a cursor (`next_since`) |
| `POST components/validate`, `components/normalize`; `GET introspect/components`; `POST cel/evaluate` | `components:read` | Studio validation, code introspection, CEL preview |
| `GET registry/{type}/{name}/source` | `registry:read` | source of a registry entry, and whether Studio may build with it |

```bash
curl http://127.0.0.1:7777/agnostic/v1/capabilities   # without a key; with one, use a config:read token
```

To try Slack notifications locally, `just up` also starts a Slack mock on <http://localhost:8030>. Add a Slack channel
in Settings › Notifications with bot token `xoxb-dev` and API base `http://localhost:8030/api` (or the incoming
webhook `http://localhost:8030/hooks/dev`), route `refund_customer` approvals to yourself with Slack on, ask
support-triage for a refund, and the message with Approve and Reject buttons appears on the mock's page.

## Run one runtime by hand

```bash
cd runtime
RUNTIME_ID=dev-prod RUNTIME_PORT=7777 uv run python -m app.main
JWT_VERIFICATION_KEY="$(cat .jwt/dev-prod.pem)" RUNTIME_ID=dev-prod uv run python -m app.main   # with JWT
```

Settings (`RUNTIME_*`): `ID`, `NAME`, `HOST`, `PORT`, `DATABASE_URL` (`postgresql+psycopg://…`), `REDIS_URL`,
`INTERNAL_SERVICE_TOKEN`, `USER_ISOLATION` (unset: on for `dev-prod`, off otherwise), `JWT_ISSUER` (optional `iss`
check), `MAX_CONCURRENCY`, `FAULTS` (development: `web_search=timeout` makes `web_search` time out). Set
`JWT_VERIFICATION_KEY` (PEM) or `JWT_JWKS_FILE` to switch on JWT authorization (`auth_mode=jwt`, audience =
`RUNTIME_ID`).

## As a container

The image installs the bridge from the repository, passed as a named build context:

```bash
docker build --build-context bridge=bridge -t agnostic-runtime:dev runtime
docker run --rm -p 7777:7777 \
  -e RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@host.docker.internal:5432/agentos_prod \
  -e RUNTIME_REDIS_URL=redis://host.docker.internal:6379/1 agnostic-runtime:dev
```

Add `-e JWT_VERIFICATION_KEY="$(cat runtime/.jwt/dev-prod.pem)"` to make it trust your control plane.
