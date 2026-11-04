# Runbook: instance unreachable

## Symptoms

- The instance shows *Unreachable* in the switcher and on *Instances*; pages for it show "didn't answer".
- Calls fail with `502 instance_unreachable`, or "failed several times in a row; retrying in N s" (the gateway's
  circuit breaker opened after repeated failures).
- `agnostic_gateway_upstream_duration_seconds_count{outcome="unreachable"}` or `{outcome="error"}` rises for the
  instance.

## Confirm

1. *System › Endpoints › Check endpoints*, or from a shell where the API runs:

   ```bash
   agnostic config check --connect      # look for "instance <slug>"
   ```

2. *Settings › Connection › Test connection* on the instance: it runs DNS, TCP, TLS, `/info`, the token check and
   the scope check, and names the step that fails with a hint.

## Fix by failing step

| Step | Usual cause | Fix |
|---|---|---|
| DNS | the endpoint name doesn't resolve from the API's network | fix DNS, or the endpoint URL in *Settings › Connection* |
| Connect | the runtime is down, a firewall or NetworkPolicy blocks it | start the runtime; allow the API and workers to reach it (the chart's `networkPolicy.egress.runtimes`) |
| TLS | an untrusted or expired certificate; the proxy wants a client certificate | add the CA bundle (instance) or `AGNOSTIC_TLS__CA_FILE` (org); renew; add a [client certificate](../admin/instances-and-keys.md) |
| AgentOS | the URL points at something else, or AgentOS fails to start | check the runtime's logs and `GET /health` |
| Token (401) | the runtime doesn't trust the current key, or audience/issuer differ | copy `JWT_VERIFICATION_KEY` and the audience/issuer from *Settings › Connection*; finish or cancel a staged key rotation |
| Scopes | the runtime accepts tokens without scopes | turn `authorization` on in AgentOS |
| Version | the agno minor changed | re-run *Test connection*; check the release notes for supported versions |

A runtime that is only slow: compare `agnostic_gateway_upstream_duration_seconds` with the runtime's own metrics,
and its queue (*Queue*). The gateway's read timeout is `AGNOSTIC_GATEWAY__UPSTREAM_READ_TIMEOUT`.

## Verify

*Test connection* passes, the instance turns *Connected* within a minute (health is polled every minute), and the
circuit breaker closes on the next successful call.
