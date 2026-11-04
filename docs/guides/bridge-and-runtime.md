# Bridge and runtime

Agnostic manages AgentOS runtimes you build and run. Two things help: **agnostic-bridge**, a package you install in
your AgentOS app, and **agnostic-runtime**, a template AgentOS app to start from.

## agnostic-bridge

The bridge adds routes under `/agnostic/v1` for what AgentOS doesn't expose itself: capability discovery,
component validation and normalisation with agno's own loader, file provenance, evaluations, worker and scheduler
details, the approval and schedule event feed, introspection of components defined in code, and CEL evaluation. Its
routes are guarded by AgentOS's own authorization and keep no state.

Without the bridge everything still works; some checks fall back to the control plane's own (and say so), and a few
details are unavailable (workers per replica, the event feed, file provenance).

```bash
pip install agnostic-bridge      # or uv add agnostic-bridge
```

```python
from agno.os import AgentOS
from agno.os.authz import Authorization
from agnostic_bridge import install

agent_os = AgentOS(
    ...,
    authorization=Authorization(algorithm="RS256", verify_audience=True, audience="my-os",
                                issuer="https://agnostic.example.com"),
)
app = install(agent_os)          # instead of agent_os.get_app()
```

| agnostic-bridge | Agno | Python |
|---|---|---|
| 1.0.x | 3.1.x (3.1.12 or newer) | 3.10–3.13 |

It depends on compatible ranges (`agno[os]>=3.1.12,<3.2`, FastAPI, pydantic), so it installs into existing apps. A new
agno minor needs a new bridge release.

For [direct mode](admin/direct-mode.md), add CORS for the control plane's origin and keep AgentOS's decision log:

```python
from agnostic_bridge import direct_mode_cors

agent_os = AgentOS(..., authorization=Authorization(..., audit=True),
                   cors=direct_mode_cors(["https://agnostic.example.com"]))
```

## The runtime template

`agnostic-runtime` is the reference AgentOS app: sample agents, teams and workflows, a sync `PostgresDb` (Studio
needs it), tracing, the scheduler, a durable queue with Redis coordination, a `Registry` and the bridge. Copy it,
replace `app/agents`, `app/teams` and `app/workflows` with yours, and deploy it like any AgentOS. Agnostic never
ships or operates it.

Each release publishes it as a source tree (`scripts/export_runtime_template.sh` builds it with the published bridge
as a dependency).

| Setting | Does |
|---|---|
| `RUNTIME_ID`, `RUNTIME_NAME`, `RUNTIME_DESCRIPTION` | the AgentOS id (the JWT audience Agnostic mints for), name and description |
| `RUNTIME_HOST`, `RUNTIME_PORT` | where it listens (`127.0.0.1:7777`) |
| `RUNTIME_DATABASE_URL` | the runtime's own PostgreSQL (with pgvector) |
| `RUNTIME_REDIS_URL` | the runtime's Redis (queue coordination) |
| `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` | turns per-user authorization on: Agnostic's public key for this instance |
| `RUNTIME_JWT_ISSUER` | require this `iss`: Agnostic's public URL |
| `RUNTIME_USER_ISOLATION` | each user sees only their own sessions and memories (unset: on only for the id `dev-prod`) |
| `RUNTIME_INTERNAL_SERVICE_TOKEN` | the scheduler's token for calling the runtime itself |
| `RUNTIME_MAX_CONCURRENCY` | runs a worker executes at once |
| `RUNTIME_CORS_ORIGINS` | direct mode: Agnostic's origin(s), comma-separated |
| `RUNTIME_AUTHZ_AUDIT` | keep AgentOS's authorization decision log for Agnostic to ingest |

```bash
uv sync
RUNTIME_DATABASE_URL=postgresql+psycopg://… RUNTIME_REDIS_URL=redis://… uv run python -m app.main
docker build -t my-agentos .
```

## Connecting a runtime

1. Deploy the runtime and make it reachable from the Agnostic API (and from browsers, for direct mode).
2. *Instances › Connect* with its URL. Agnostic discovers it and generates its key pair.
3. Set `JWT_VERIFICATION_KEY` (and `RUNTIME_JWT_ISSUER`) on the runtime from the connect wizard or *Settings ›
   Authorization*, and restart it.
4. *Test connection*.

Details, key rotation and TLS: [Instances and keys](admin/instances-and-keys.md).
