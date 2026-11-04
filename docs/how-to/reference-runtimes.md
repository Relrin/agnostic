# Run the reference runtimes

For running your own AgentOS with the bridge in production, see [bridge and runtime](../guides/bridge-and-runtime.md);
this page is about the two development runtimes.

`just runtimes` starts two AgentOS instances from `runtime/` against the dev stack:

| Instance | URL | Database | Redis | Plays | User isolation |
|---|---|---|---|---|---|
| `dev-prod` | <http://127.0.0.1:7777> | `agentos_prod` | db 1 | production | on |
| `dev-staging` | <http://127.0.0.1:7778> | `agentos_staging` | db 2 | staging | off |

Both databases (with pgvector) are created by `deploy/dev/initdb/10-databases.sql` the first time the Postgres
volume is initialised. If your volume predates that script, run `just nuke && just up`.

```bash
just up
just runtimes                     # Ctrl+C stops both
curl http://127.0.0.1:7777/info   # agno_version 3.1.12, 6 agents, 3 teams, 3 workflows
just test-contract                # against dev-prod; pass url=http://127.0.0.1:7778 for staging
```

Until they trust a control plane (next section) the runtimes run with `auth_mode=none`, so you can call them
directly. Try the approval flow:

```bash
curl -X POST http://127.0.0.1:7777/agents/billing-agent/runs \
  -F message="please refund 19.99 to cus_42" -F stream=false -F user_id=u1
# → "status": "PAUSED"
curl http://127.0.0.1:7777/approvals          # the pending refund_customer approval
```

Interactive API docs are at `/docs` on each runtime.

## Sample components

Every component runs on `MockModel` (`runtime/app/models/mock.py`), so runs are deterministic and never call an LLM.
All of them set `store_events=True`, so `/resume` can replay a run from the database after AgentOS's in-memory event
buffer has evicted it.

| Kind | Id | What it does |
|---|---|---|
| agent | `support-triage` | Triage with `lookup_order`, `search_knowledge` and `refund_customer` (`@approval`: the run pauses) |
| agent | `billing-agent` | Billing questions; refunds through `refund_customer` |
| agent | `kb-researcher`, `web-researcher`, `qa-reviewer`, `summarizer` | One tool each (or none), canned answers |
| team | `research-team` | `TeamMode.coordinate` over kb-researcher, web-researcher, summarizer |
| team | `escalation-team` | `TeamMode.route` over billing-agent, qa-reviewer |
| team | `onboarding-team` | `TeamMode.tasks` over kb-researcher and summarizer: creates a task per member, runs them, completes |
| workflow | `ticket-router` | Step `triage`, then a `Router` that pauses for route selection (`billing` or `research`) |
| workflow | `daily-brief` | research-team, then summarizer |
| workflow | `refund-review` | Step `triage`, a `Loop` over kb-researcher (at most 2 iterations), then step `approve` with HITL |

How the mock model behaves:

- It calls a tool when the latest user message names its trigger word and the tool is attached: `refund` →
  `refund_customer`, `order` → `lookup_order`, `search` → `search_knowledge`, `web` → `web_search`. After a tool
  result it answers `Done. <result>`; otherwise `[<persona>] <phrase>: <your message>`.
- The refund amount is the number right after `refund` (`refund 49`, `refund of $12.50`) or after `$`; failing that,
  the first standalone number (ids like `cus_42` or `ord_7` don't count); failing that, `42`. So
  `order 4471, refund 49 to cus_7` refunds 49 to `cus_7`.
- As the leader of a tasks-mode team it creates one task per member, executes them in member order, then calls
  `mark_all_complete`, so a run emits `TaskCreated`, `TaskUpdated` and the member runs. Coordinate and route teams
  answer without delegating.

The workflow pauses you can drive from Chat (or with `continue_run` in agno):

- **`support-triage` in a step**: a message with `refund` pauses the `triage` step on the `refund_customer` approval.
- **`ticket-router`, step `route`**: route selection. The run pauses with `available_choices` `billing` and
  `research` and continues with the route you pick. agno doesn't evaluate the CEL selector while route selection is
  on; it stays in the config.
- **`refund-review`, loop `research`**: ends early once kb-researcher's answer mentions a help-center article,
  otherwise after the second pass.
- **`refund-review`, step `approve`**: confirmation plus user input (`amount: float`, `reason: str`), then output
  review of `Refund of <amount> approved: <reason>.`

`just seed` also creates the DB component `support-triage-studio` on both runtimes, through the gateway and AgentOS's
`/components` API: published versions v1-v3 (v3 current) and a draft v4, all on the registry's `agnostic-mock`
model and tools. It gives Chat's version and draft selectors something to show.

## Connect them to your control plane

The control plane signs a short-lived RS256 JWT for every call it makes to a runtime, with a key pair per
instance. A runtime trusts it through the public key in `JWT_VERIFICATION_KEY` and then checks each token's
`aud` (its own id), `iss` (the control plane's public URL) and scopes. `just seed` does the connect wizard for both
runtimes and hands them their keys:

```bash
just up && just migrate
just dev                          # terminal 1: API + web app
just runtimes                     # terminal 2: both runtimes, still auth_mode=none
just bootstrap                    # once: org "Localhost Company", Owner daniel@localhost.company
just seed                         # connects dev-prod (production) and dev-staging (staging),
                                  # writes runtime/.jwt/dev-prod.pem and dev-staging.pem,
                                  # creates support-triage-studio v1-v3 (+ draft v4) on both
# restart `just runtimes` (Ctrl+C, run it again): it prints "JWT authorization on" for each key it found
just seed --test                  # Test connection for both: token accepted, scopes enforced, capabilities
```

You can do the same in the web app: **Instances › Connect**, then **Settings › Connection › Test connection**.

- `just bootstrap` and `just seed` use `AGNOSTIC_DEV_OWNER_EMAIL` / `AGNOSTIC_DEV_OWNER_PASSWORD` from `.env`
  (defaults: `daniel@localhost.company` / `localhost-dev-password`). `just seed` talks to `http://127.0.0.1:8000`; set
  `AGNOSTIC_DEV_API_URL` or pass `--api-url` for another address.
- It's safe to run again: instances that are already connected (same slug or URL) are reused, a key file is
  only rewritten when the active key changed, and `support-triage-studio` versions that exist are left alone. Restart the runtimes whenever it says it wrote a key, for example
  after a key rotation or after you reset the control-plane database.
- `runtime/.jwt/` is git-ignored. Delete it to put the runtimes back in `auth_mode=none`.
- `just runtimes` also passes `RUNTIME_JWT_ISSUER` (from `AGNOSTIC_INSTANCES__ISSUER`, else
  `AGNOSTIC_HTTP__PUBLIC_URL`), so tokens from another control plane are rejected even if they carry the right
  audience.

Once a runtime verifies JWTs, `curl` without a token gets `401` everywhere except `/health` and `/info`; go
through the control plane's gateway (`/api/v1/instances/dev-prod/os/...`) instead.

## The bridge

Both runtimes install [`agnostic-bridge`](../../bridge) (`app = install(agent_os)` in `runtime/app/main.py`). It
adds `GET /agnostic/v1/capabilities`, which needs the `config:read` scope and reports the bridge, agno and Python
versions, the `os_id`, a replica id and the features this process runs (tracing, scheduler, durable queue, Redis
coordination, authorization, user isolation, registry, MCP, interfaces). The control plane's capability probe
treats a `2xx` as "bridge available".

```bash
curl http://127.0.0.1:7777/agnostic/v1/capabilities   # without a key; with one, use a config:read token
```

It also adds `POST /agnostic/v1/evals/run` (`evals:write`, plus run access to the target as on `POST /eval-runs`):
AgentOS's eval body with `component_type` (`agent`/`team`), `component_id` and an optional `version` instead of
`agent_id`/`team_id`. An explicit version evaluates that stored config, drafts included (the owner's or an admin's
only; anyone else gets the component's 404); no version evaluates the current component. `model_provider` +
`model_id` pick the judge of accuracy and agent-as-judge evals and never replace the component's own model (unlike
`POST /eval-runs`), so a draft and the current version are scored by the same judge. The run goes through
AgentOS's own eval helpers with the OS db, so it is stored and listed by `GET /eval-runs`; the response is the
`/eval-runs` schema plus `component_version`. It needs an AgentOS db (503 otherwise).

Two more routes feed the Control pages:

- `GET /agnostic/v1/workers` (`agent_os:admin`, like AgentOS's own `/queue/*`) describes *this* replica: its replica
  id, the queue worker id that appears in a job's `locked_by`, deployment id, concurrency, in-flight jobs, the full
  `QueueConfig` (depth, attempts, delays, timeouts, `lock_grace_seconds`, stop timeout, poll interval, retention)
  and whether the scheduler runs and how often it polls. Behind a load balancer each call reaches one replica; the
  Queue page merges what several calls returned with the workers it sees in `locked_by` of running jobs.
- `GET /agnostic/v1/events?since=&limit=` (`approvals:read` and `schedules:read`) lists approvals created and
  scheduled runs that failed since an epoch-seconds cursor, newest last, with `next_since`. The control plane's
  schedule-failure watcher uses it instead of listing every schedule's runs.

To try Slack notifications locally, `just up` also starts a Slack mock on http://localhost:8030. Add a Slack channel
in Settings › Notifications with a bot token `xoxb-dev` and API base `http://localhost:8030/api` (or an incoming
webhook `http://localhost:8030/hooks/dev`), route `refund_customer` approvals to yourself with Slack on, ask
support-triage for a refund, and the message with its Approve and Reject buttons shows up on the mock's page.

The bridge is a separate package (`bridge/`, its own `uv` project, Python 3.10-3.13 like agno) that customers add
to their own AgentOS: `pip install agnostic-bridge`, then serve `install(agent_os)` instead of
`agent_os.get_app()`. It mounts its routes ahead of AgentOS's MCP catch-all and registers their scopes in AgentOS's
own route-scope table, so they're protected exactly like the built-in routes. `runtime/` uses it from the
repository as an editable path dependency.

## Run one runtime by hand

```bash
cd runtime
RUNTIME_ID=dev-prod RUNTIME_PORT=7777 uv run python -m app.main
JWT_VERIFICATION_KEY="$(cat .jwt/dev-prod.pem)" RUNTIME_ID=dev-prod uv run python -m app.main   # with JWT
```

Settings (`RUNTIME_*`): `ID`, `NAME`, `HOST`, `PORT`, `DATABASE_URL` (`postgresql+psycopg://…`), `REDIS_URL`,
`INTERNAL_SERVICE_TOKEN`, `USER_ISOLATION` (unset: on for `dev-prod`, off otherwise), `JWT_ISSUER` (optional
`iss` check), `MAX_CONCURRENCY`, `FAULTS` (development: `web_search=timeout` makes `web_search` time out, so
`just seed --trigger-daily-brief` produces the failing daily-brief run Ask your OS explains). Set
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
