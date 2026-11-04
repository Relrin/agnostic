# Identity, access and the gateway

People sign in, belong to the installation's one org with an org role, connect AgentOS instances with
per-instance keys, and call any AgentOS route through the gateway with a JWT carrying exactly their scopes. Every
change and denial is audited. Groups, editable roles, service accounts, SAML and MFA: [access governance](access-governance.md).

## Modules

| Module | Owns | Tables |
|---|---|---|
| `audit` | append-only events, action vocabulary, `AuditLog.record` / `record_now`, retention | `audit_events` |
| `settings` | org settings (`require_explicit_bindings`, `audit_log_all_reads`, …) | `settings_org`, `settings_flags` |
| `identity` | accounts, argon2id passwords, sessions and CSRF, SSO (OIDC, GitHub), password reset, `/me` | `identity_*` |
| `instances` | registry, probe and test, sealed RS256 keys, JWKS, health polling, `/config` snapshots, capabilities, network mode | `inst_*` |
| `org` | profile, members and org roles, invitations, seats, `agnostic bootstrap` | `org_profile`, `org_members`, `org_invitations` |
| `access` | scope catalog, roles, bindings, cached effective scopes, `Authorizer`, explain | `access_*` |
| `gateway` | `ANY /api/v1/instances/{instance}/os/{path}`, route policies, JWT minting, caching, rate limits, circuit breaker, elevation, direct-mode tokens | `gw_route_policies` |

## Signing in

- **Local accounts** on by default (`AGNOSTIC_IDENTITY__LOCAL_LOGIN`); argon2id off the event loop; 12+ characters.
- **SSO**: GitHub (OAuth 2, verified primary email) and OIDC for any IdP (PKCE, `state`, `nonce`, `id_token` checked
  against the JWKS). See [sign-in providers](../how-to/sign-in-providers.md).
- **Joining**: a pending invitation for the verified email, or JIT when the provider allows the domain; otherwise
  `/login?error=not_invited`.
- **Sessions**: opaque `HttpOnly`, `SameSite=Lax` cookie; the ephemeral store keeps its SHA-256 (sliding 12 h,
  absolute 7 d), `identity_sessions` a copy for revocation. Unsafe requests need `X-CSRF-Token` matching the
  `agnostic_csrf` cookie.
- **Lockout**: 5 failures lock an email for 15 minutes; 30 attempts a minute per IP.
- **First run**: `agnostic bootstrap --org-name …` creates the org and the Owner (`--owner-email`) or a 24 h
  `/onboarding?token=…` link.

![Sign-in and session: password and SSO sign-in, MFA, session cookie and CSRF, enforced SSO and break-glass](images/sign-in-session.svg)

## Invitations

`org/application/invitations.py`, `/api/v1/invitations`:

- `POST` takes `delivery: "email" | "link"` (default `email`) and returns `accept_url` (shown once; only its SHA-256
  is stored) and `email_sent`; a failed SMTP send keeps the link (`email_sent: false`). `GET /api/v1/org` reports
  `email_delivery`.
- `POST /{id}/link` issues a new link without email (audit `invitations.link`); `POST /{id}/resend` emails one. The
  old link stops working.
- `POST /{token}/accept` with a password is refused (`sso_required`, `local_login_disabled`) when SSO is enforced or
  local login is off, since a forwarded link proves nothing: the invitee joins via SSO by verified email.
- Invitations expire after 7 days and may carry role bindings and groups, applied on acceptance.
- UI: "Send by email" / "Create link only"; pending rows have "Copy new link" (confirmed) and "Resend" (only with
  email configured).

![Invitation flow: invite by email or link, preview, accept with a password or join via SSO, 'Copy new link'](images/invitation-flow.svg)

## Who may do what

- **Org roles** (Owner, Administrator, Member) carry control-plane scopes (`org:*`, `os:*`, `audit:read`,
  `settings:*`). Only Owners have `os:delete`, `os:keys:rotate`, `org:delete`; the last Owner can't leave.
- **Access roles** are sets of AgentOS scopes **bound** to a person on one instance or all, optionally expiring.
  Owners and Administrators have implicit `agent_os:admin` unless `require_explicit_bindings` is on.

Effective scopes are the union of bindings plus implicit access, matched as AgentOS does (`agents:run` covers
`agents:<id>:run`), cached 60 s under an **access generation** every access change bumps. A denial is a 403
`scope_missing` with `required_scopes`, `missing_scopes` and a sentence naming a role that would grant it;
`POST /api/v1/access/explain` answers for anyone.

## Instances and trust

1. **Probe** (`POST /instances/probe`): DNS, `/health`, `/info`; nothing stored.
2. **Connect** (`POST /instances`): `pending`, plus an RS256 key pair (3072-bit) whose private key is sealed and never
   leaves the API process.
3. **Trust**: the runtime gets `JWT_VERIFICATION_KEY` and `Authorization(verify_audience=True, audience=<os_id>,
   issuer=<public url>)` (`GET …/keys/public` gives both).
4. **Test** (`POST …/test`): a `config:read` token must work and a scope-less one must be refused; then `connected`,
   with `/config` and capabilities snapshotted.

Rotation is `stage` → `activate`; `/.well-known/agnostic/instances/{id}/jwks.json` lists both keys meanwhile.
AgentOS loads `JWT_JWKS_FILE` only at startup (nothing refreshes it), so the runtime is restarted with that document
before activation. Health is polled every minute (`connected` ↔ `unreachable`), snapshots every five.

![Instance lifecycle: probe, register, key stage and activate, reachable and unreachable, rotation](images/instance-lifecycle.svg)

## The gateway

`agnostic_gateway/application/proxy.py`: route policy (method + path → scopes, cache TTL, audit level, rate bucket,
seeded from agno 3.1.12; unknown routes need `agent_os:admin`), scope pre-check (denials never reach the runtime),
rate limit, circuit breaker, a 5-minute JWT (`aud` = os_id, scopes trimmed to the route family past 8 KB, cached under
the access generation), the streamed proxy, error mapping (`capability_disabled`, `instance_auth_failed`,
`instance_unreachable`), and audit (writes and denials always, reads sampled).

![Gateway pipeline: resolve instance, route policy, effective scopes, JWT mint, proxy, audit, fail closed](images/gateway-pipeline.svg)

- Runtimes in `none` or `security_key` auth mode admit Instance admins only.
- Cookies, the caller's `Authorization` and hop-by-hop headers are dropped; SSE gets `: keepalive` comments; the
  database session closes before streaming.
- Small GETs are cached per scope set; any write invalidates the instance's cache.
- **Direct mode** (`network_mode=direct`): `POST …/instances/{instance}/token` gives the browser the same JWT to call
  the runtime itself (CORS via the bridge's `direct_mode_cors`); audit relies on AgentOS's decision log.
- **Delegated elevation**: typed actions (approval decisions, queue operations, draft test runs) may act as Instance
  admin for one request ([operate](operate-and-realtime.md#delegated-elevation)); the passthrough never elevates.

## Audit

`audit_events` is append-only (a PostgreSQL trigger refuses `UPDATE`/`DELETE`) and partitioned by month; a daily job
adds partitions and drops those past retention (400 days). Modules call `AuditLog.record(...)` in their transaction,
or `record_now(...)` for denials; summary templates come from `audit_actions()`.
