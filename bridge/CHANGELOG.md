# Changelog

## 0.1.0

First release, for Agno AgentOS 3.1.x.

- Routes under `/agnostic/v1`: capabilities, component validate/normalize, evals, file provenance, workers,
  events, code-component and registry introspection, CEL evaluation.
- `direct_mode_cors()`: CORS for the control plane's origin when browsers call AgentOS directly.
- Dependencies are compatible ranges (`agno[os]>=3.1.12,<3.2`, FastAPI, pydantic) instead of exact pins, so the
  bridge installs into existing AgentOS apps.
