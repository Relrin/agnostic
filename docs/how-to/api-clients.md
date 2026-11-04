# Regenerate API clients

Two clients are generated, and both are committed so reviews show their diffs.

## Frontend client (control-plane OpenAPI → TypeScript)

The OpenAPI document is the contract between backend and frontend.

```bash
just api-gen
```

This runs `agnostic openapi --out frontend/packages/api/openapi.json`, then `yarn api:gen` (`@hey-api/openapi-ts`:
fetch client, types, SDK functions and TanStack Query options in `packages/api/src/generated`), then
`scripts/render_api_reference.py`, which rewrites [`docs/reference/api.md`](../reference/api.md). Run it whenever you
change a route, a schema or a module's routers.

`just api-check` (CI's **api-drift** job) regenerates everything and fails if `frontend/packages/api` or
`docs/reference/api.md` differ from what's committed.

Operation ids are `<tag>_<function name>` (`instances_list_instances` → `instancesListInstancesOptions`), so name
route functions for what they do.

## AgentOS client (runtime OpenAPI → Python models)

`agnostic_agentos_client/_generated/models.py` comes from the pinned AgentOS version's OpenAPI.

```bash
just agentos-client-gen
```

This dumps the reference runtime's OpenAPI to
`backend/packages/agnostic-agentos-client/openapi/agentos-3.1.12.json` and regenerates the models with
datamodel-code-generator. Do it when upgrading agno ([runtime and client](../architecture/agentos-runtime-and-client.md)),
then run `just test-contract`.
