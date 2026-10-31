# Run the reference runtimes

`just runtimes` starts two AgentOS instances from `runtime/` against the dev stack:

| Instance | URL | Database | Redis |
|---|---|---|---|
| `dev-prod` | <http://127.0.0.1:7777> | `agentos_prod` | db 1 |
| `dev-staging` | <http://127.0.0.1:7778> | `agentos_staging` | db 2 |

Both databases (with pgvector) are created by `deploy/dev/initdb/10-databases.sql` the first time the Postgres
volume is initialised. If your volume predates that script, run `just nuke && just up`.

```bash
just up
just runtimes                     # Ctrl+C stops both
curl http://127.0.0.1:7777/info   # agno_version 3.1.12, 6 agents, 2 teams, 2 workflows
just test-contract                # against dev-prod; pass url=http://127.0.0.1:7778 for staging
```

Try the approval flow:

```bash
curl -X POST http://127.0.0.1:7777/agents/billing-agent/runs \
  -F message="please refund 19.99 to cus_42" -F stream=false -F user_id=u1
# → "status": "PAUSED"
curl http://127.0.0.1:7777/approvals          # the pending refund_customer approval
```

Interactive API docs are at `/docs` on each runtime.

## Run one runtime by hand

```bash
cd runtime
RUNTIME_ID=dev-prod RUNTIME_PORT=7777 uv run python -m app.main
```

Settings (`RUNTIME_*`): `ID`, `NAME`, `HOST`, `PORT`, `DATABASE_URL` (`postgresql+psycopg://…`), `REDIS_URL`,
`INTERNAL_SERVICE_TOKEN`, `USER_ISOLATION`, `MAX_CONCURRENCY`. Set `JWT_VERIFICATION_KEY` to switch on JWT
authorization (`auth_mode=jwt`).

## As a container

```bash
docker build -t agnostic-runtime:dev runtime
docker run --rm -p 7777:7777 \
  -e RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@host.docker.internal:5432/agentos_prod \
  -e RUNTIME_REDIS_URL=redis://host.docker.internal:6379/1 agnostic-runtime:dev
```
