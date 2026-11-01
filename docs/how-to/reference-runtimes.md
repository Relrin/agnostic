# Run the reference runtimes

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
curl http://127.0.0.1:7777/info   # agno_version 3.1.12, 6 agents, 2 teams, 2 workflows
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
                                  # writes runtime/.jwt/dev-prod.pem and dev-staging.pem
# restart `just runtimes` (Ctrl+C, run it again): it prints "JWT authorization on" for each key it found
just seed --test                  # Test connection for both: token accepted, scopes enforced, capabilities
```

You can do the same in the web app: **Instances › Connect**, then **Settings › Connection › Test connection**.

- `just bootstrap` and `just seed` use `AGNOSTIC_DEV_OWNER_EMAIL` / `AGNOSTIC_DEV_OWNER_PASSWORD` from `.env`
  (defaults: `daniel@localhost.company` / `localhost-dev-password`). `just seed` talks to `http://127.0.0.1:8000`; set
  `AGNOSTIC_DEV_API_URL` or pass `--api-url` for another address.
- It's safe to run again: instances that are already connected (same slug or URL) are reused, and a key file is
  only rewritten when the active key changed. Restart the runtimes whenever it says it wrote a key, for example
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
`iss` check), `MAX_CONCURRENCY`. Set `JWT_VERIFICATION_KEY` (PEM) or `JWT_JWKS_FILE` to switch on JWT authorization
(`auth_mode=jwt`, audience = `RUNTIME_ID`).

## As a container

The image installs the bridge from the repository, passed as a named build context:

```bash
docker build --build-context bridge=bridge -t agnostic-runtime:dev runtime
docker run --rm -p 7777:7777 \
  -e RUNTIME_DATABASE_URL=postgresql+psycopg://agnostic:agnostic@host.docker.internal:5432/agentos_prod \
  -e RUNTIME_REDIS_URL=redis://host.docker.internal:6379/1 agnostic-runtime:dev
```

Add `-e JWT_VERIFICATION_KEY="$(cat runtime/.jwt/dev-prod.pem)"` to make it trust your control plane.
