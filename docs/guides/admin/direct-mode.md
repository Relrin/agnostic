# Direct mode

In the default **gateway** mode, every browser call to a runtime goes through the control plane: it checks the
person's scopes, explains a denial, caches responses, rate-limits, audits and mints the token. In **direct** mode the
browser asks the control plane for a short-lived token and calls the runtime itself. AgentOS still enforces the
person's scopes, which are exactly those the gateway would have put in its token.

Use it when the extra hop matters (a runtime far from the control plane, very high stream volume) and the runtime is
reachable from people's browsers. Keep the gateway when the runtime should stay on a private network.

## What changes

| | Gateway | Direct |
|---|---|---|
| Who reaches the runtime | the API only | every signed-in browser |
| Scope enforcement | gateway pre-check, then AgentOS | AgentOS |
| Denial explanations ("needs `sessions:write` on prod, ask Dana") | yes | no: AgentOS's 403 |
| Response cache, rate limits, circuit breaker | yes | no |
| Delegated elevation for typed actions | yes | no |
| Audit | every write and denial, sampled reads | the token issue, plus AgentOS's decision log ingested |

Control-plane features that call runtimes themselves (Home, the approvals inbox, schedules, Studio, evaluations)
keep going through the control plane in both modes.

## Requirements

1. **TLS.** In production the browser URL must be `https://`. The control plane refuses to switch an instance to
   direct mode otherwise.
2. **CORS** for the control plane's origin. With the reference runtime, set `RUNTIME_CORS_ORIGINS`:

   ```bash
   RUNTIME_CORS_ORIGINS=https://agnostic.example.com
   ```

   In your own AgentOS app, use the bridge helper:

   ```python
   from agnostic_bridge import direct_mode_cors

   agent_os = AgentOS(..., cors=direct_mode_cors(["https://agnostic.example.com"]))
   ```

3. **The decision log**, so direct calls still reach the audit log: `Authorization(..., audit=True)` in AgentOS
   (`RUNTIME_AUTHZ_AUDIT=true` in the reference runtime). The worker ingests AgentOS's authorization decisions into
   the audit log; the System page warns when ingestion falls behind.

## Switch an instance

*Settings › Connection › Network*: choose *Direct* and, when browsers reach the runtime at another address than the
control plane does (a cluster-internal `endpoint_url`), the **browser URL**. The change is audited. Through the
API: `PATCH /api/v1/instances/{id}` with `network_mode` and `browser_url`.

The web app then calls `POST /api/v1/instances/{id}/token` (needs a signed-in person, `Cache-Control: no-store`):

```json
{"token": "eyJ…", "expires_at": "2026-11-04T10:15:00Z", "base_url": "https://agentos.example.com"}
```

and sends `Authorization: Bearer <token>` to `base_url`, without cookies. Tokens are cached and refreshed 30 seconds
before they expire; a 401 from the runtime gets one retry with a fresh token. Each issue is audited
(`gateway.direct_token`) and limited to 30 a minute per person and instance. Service accounts can't get direct-mode
tokens.

The web app's content security policy only lets it connect to its own origin. Browser URLs of direct-mode
instances are added to `connect-src` automatically (within 30 seconds on every API replica); other origins can be
added with `AGNOSTIC_HTTP__CSP_EXTRA_CONNECT`.
