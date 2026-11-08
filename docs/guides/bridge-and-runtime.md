# Bridge and runtime

Agnostic manages AgentOS runtimes you build and run. Two things help: **agnostic-bridge**, a package you install in
your AgentOS app, and **agnostic-runtime**, a template AgentOS app to start from.

## agnostic-bridge

The bridge adds routes under `/agnostic/v1` for what AgentOS doesn't expose itself: capability discovery,
component validation and normalisation with agno's own loader, file provenance, evaluations, worker and scheduler
details, the approval and schedule event feed, introspection of components defined in code, CEL evaluation, and the
list of artefacts (files agents produced) a session's runs stored. Its routes are guarded by AgentOS's own
authorization and keep no state. Its `agnostic_bridge.artifacts` package collects the files agents write into run
media (`collect_artifacts`, `ArtifactTools`, `capture_artifacts`; the repository's `docs/how-to/collect-artefacts.md`
has recipes for folders, E2B, Claude Code, Codex, Pi and OpenCode).

Without the bridge everything still works; some checks fall back to the control plane's own (and say so), and a few
details are unavailable (workers per replica, the event feed, file provenance, artefacts).

The bridge isn't on a package index: build it from the Agnostic repository and install the wheel into your AgentOS
app's image (the runtime template's `Dockerfile` does the same from the repository's `bridge/` directory):

```bash
uv build bridge --wheel --out-dir dist                       # from the repository root
uv add ./dist/agnostic_bridge-0.1.0-py3-none-any.whl         # in your AgentOS app
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
| 0.1.x | 3.1.x (3.1.12 or newer) | 3.10–3.13 |

It depends on compatible ranges (`agno[os]>=3.1.12,<3.2`, FastAPI, pydantic), so it installs into existing apps. A new
agno minor needs a new bridge version.

For [direct mode](admin/direct-mode.md), add CORS for the control plane's origin and keep AgentOS's decision log:

```python
from agnostic_bridge import direct_mode_cors

agent_os = AgentOS(..., authorization=Authorization(..., audit=True),
                   cors=direct_mode_cors(["https://agnostic.example.com"]))
```

### The tool catalog

Approved MCP servers and Agno toolkits from the control plane's tool catalog (*Access › Tool catalog*) reach a runtime
through its bridge: it pulls the entries for its instance, builds them and adds them to the registry, where Studio
lists them as tool blocks. It is off until these are set on the runtime; *Tool catalog › Instances › Set up sync*
shows them, with a token that only reads this instance's catalog:

| Variable | Meaning |
|---|---|
| `AGNOSTIC_CONTROL_PLANE_URL` | The control plane's public URL (the runtime must reach it). |
| `AGNOSTIC_INSTANCE_ID` | This instance's id in the control plane. |
| `AGNOSTIC_TOOL_CATALOG_TOKEN` | The sync token (`agn_pat_…`, scope `tool_catalog:sync` on this instance). |
| `AGNOSTIC_TOOL_CATALOG_ENV` | The environment variables catalog entries may read, comma-separated (`LINEAR_TOKEN,GITHUB_*`). None by default; `AGNOSTIC_*` never. |
| `AGNOSTIC_TOOL_CATALOG_INTERVAL` | Seconds between pulls (default 60, at least 10). The control plane also asks for a pull after a change. |
| `AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL` | `true` to build tools that run commands here: stdio MCP servers and the shell, python, file and docker toolkits. Off by default. |
| `AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS` | Commands stdio servers may start (default `npx,uvx`). |
| `AGNOSTIC_TOOL_CATALOG_CACHE` | A file for the last good catalog, so a restart builds the tools while the control plane is away. |
| `AGNOSTIC_CONTROL_PLANE_CA_BUNDLE` | A CA bundle for the control plane's certificate. |

Entries never carry secrets: a credential is the name of an environment variable the runtime reads (an entry with
`Authorization: {"env": "LINEAR_TOKEN"}` needs `LINEAR_TOKEN` set here and listed in `AGNOSTIC_TOOL_CATALOG_ENV`).
The list is what keeps an entry from sending any other variable of the runtime to a server of its choosing. Stdio
servers get only the variables their entry names, plus `PATH`, `HOME` and the like. Each entry's state (`connected`,
`missing_env`, `stdio_disabled`, `failed`, `conflict`) shows on the instance's catalog status and on its Studio block.
Toolkits that need a package (`ddgs`, `pygithub`, …) must be installed in the runtime's image. The design is in
[ADR-034](../adr/0034-tool-catalog-pulled-by-the-bridge.md).

## The runtime template

`agnostic-runtime` is the reference AgentOS app: sample agents, teams and workflows, a sync `PostgresDb` (Studio
needs it), tracing, the scheduler, a durable queue with Redis coordination, a `Registry` and the bridge. Copy it,
replace `app/agents`, `app/teams` and `app/workflows` with yours, and deploy it like any AgentOS. Agnostic never
ships or operates it.

Each release publishes it as a source tree (`scripts/export_runtime_template.sh`): `runtime/` next to the `bridge/`
source it builds into its image, so it needs no package index for the bridge.

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
docker build --build-context bridge=../bridge -t my-agentos .   # from runtime/
```

## Connecting a runtime

1. Deploy the runtime and make it reachable from the Agnostic API (and from browsers, for direct mode).
2. *Instances › Connect* with its URL. Agnostic discovers it and generates its key pair.
3. Set `JWT_VERIFICATION_KEY` (and `RUNTIME_JWT_ISSUER`) on the runtime from the connect wizard or *Settings ›
   Authorization*, and restart it.
4. *Test connection*.

Details, key rotation and TLS: [Instances and keys](admin/instances-and-keys.md).
