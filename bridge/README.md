# agnostic-bridge

Companion routes for an [Agno](https://github.com/agno-agi/agno) AgentOS, used by the Agnostic control plane for
what AgentOS itself doesn't expose: capability discovery, component validation and normalisation, file
provenance, evals, worker and scheduler details, approval and schedule events, code-defined component
introspection and CEL evaluation.

It isn't published to a package index: it's built from this repository and installed into the image of the AgentOS
app that uses it.

- Inside the repository, `runtime/` takes it as a path dependency, and `runtime/Dockerfile` builds it into the
  runtime image (`docker build --build-context bridge=bridge -t agnostic-runtime:dev runtime`).
- In your own AgentOS app, build the wheel from the repository root and install it in your image:

  ```bash
  uv build bridge --wheel --out-dir dist
  uv add ./dist/agnostic_bridge-1.0.0-py3-none-any.whl
  ```

```python
from agno.os import AgentOS
from agno.os.authz import Authorization
from agnostic_bridge import install

agent_os = AgentOS(..., authorization=Authorization(algorithm="RS256", verify_audience=True, audience="my-os"))
app = install(agent_os)  # instead of agent_os.get_app()
```

Routes live under `/agnostic/v1` and are guarded by AgentOS's own auth layer: they need the scopes in
`agnostic_bridge.SCOPE_MAPPINGS` (`agent_os:admin` passes too). The bridge keeps no state of its own.

## Direct mode

When the control plane lets browsers call this AgentOS directly, allow its origin and keep the decision log:

```python
from agnostic_bridge import direct_mode_cors

agent_os = AgentOS(
    ...,
    authorization=Authorization(..., audit=True),
    cors=direct_mode_cors(["https://agnostic.example.com"]),
)
```

## Compatibility

| agnostic-bridge | Agno | Python | Agnostic control plane |
|---|---|---|---|
| 1.0.x | 3.1.x (3.1.12+) | 3.10 – 3.13 | 1.0.x |

The full matrix is in the Agnostic repository: `docs/reference/compatibility.md`.

License: BSD-3-Clause.
