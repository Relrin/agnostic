# Regenerate API clients

Two clients are generated, and both are committed so reviews show their diffs.

## Frontend client (control-plane OpenAPI → TypeScript)

The OpenAPI document is the contract between backend and frontend.

```bash
just api-gen
```

This runs `agnostic openapi --out frontend/packages/api/openapi.json` and then `yarn api:gen`
(`@hey-api/openapi-ts`: fetch client, types, SDK functions and TanStack Query options in
`packages/api/src/generated`). Run it whenever you change a route, a schema or a module's routers.

CI's **api-drift** job regenerates both files and fails if they differ from what's committed. `just api-check` does
the same locally.

Operation ids are `<tag>_<function name>` (e.g. `hello_list_greetings` → `helloListGreetingsOptions`), so name
route functions for what they do.

## AgentOS client (runtime OpenAPI → Python models)

The models in `agnostic_agentos_client/_generated/models.py` come from the pinned AgentOS version's OpenAPI.

```bash
just agentos-client-gen
```

This dumps the reference runtime's OpenAPI to `openapi/agentos-3.1.12.json` and regenerates the models with
datamodel-code-generator. Do it when upgrading agno ([runtime and client](../architecture/agentos-runtime-and-client.md)),
then run `just test-contract`.
