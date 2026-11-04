# agnostic-runtime

The reference Agno AgentOS app for Agnostic: the sample agents, teams and workflows, a sync `PostgresDb` (Studio
needs it), tracing, the scheduler, a durable queue with Redis coordination, a `Registry`, and `agnostic-bridge`.

It is a template: copy it, replace `app/agents`, `app/teams` and `app/workflows` with your own, and run it like
any AgentOS. Agnostic never ships or operates it.

```bash
uv sync
RUNTIME_DATABASE_URL=postgresql+psycopg://… RUNTIME_REDIS_URL=redis://… uv run python -m app.main
docker build -t my-agentos .
```

| Setting | Does |
|---|---|
| `RUNTIME_ID`, `RUNTIME_NAME` | the AgentOS id (the JWT audience the control plane mints for) and display name |
| `RUNTIME_DATABASE_URL`, `RUNTIME_REDIS_URL` | the runtime's own Postgres (with pgvector) and Redis |
| `JWT_VERIFICATION_KEY` or `JWT_JWKS_FILE` | turns per-user authorization on (the control plane's public key) |
| `RUNTIME_JWT_ISSUER` | require this `iss` (the control plane's public URL) |
| `RUNTIME_USER_ISOLATION` | each user sees only their own sessions and memories (unset: on only for the id `dev-prod`) |
| `RUNTIME_CORS_ORIGINS` | direct mode: the control plane's origin(s), comma-separated |
| `RUNTIME_AUTHZ_AUDIT` | keep AgentOS's authorization decision log (the control plane ingests it) |

Connecting it to Agnostic is described in the Agnostic guides: `docs/guides/bridge-and-runtime.md`.
