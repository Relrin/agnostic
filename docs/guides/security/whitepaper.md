# Security whitepaper

Agnostic is a self-hosted control plane for Agno AgentOS. It runs inside the customer's network, stores its state
in the customer's PostgreSQL, and calls only endpoints the customer configured. This document covers its
architecture and data flows, identity and authorization, cryptography, the threat model and the supply chain.

## Architecture

| Component | Role | State |
|---|---|---|
| `agnostic` API (one or more replicas) | HTTP API, the web app (same origin), the gateway to AgentOS | none in process; sessions in the cache |
| `agnostic` workers | background jobs: deliveries, SIEM streaming, audit maintenance, syncs, health checks | none in process |
| PostgreSQL (customer) | everything durable: identity, access, instances (sealed keys), audit log, Studio metadata, jobs | yes |
| Redis-compatible cache (customer) | sessions, caches, rate limits, realtime events | rebuildable |
| AgentOS runtimes (customer) | run agents; enforce the scopes in Agnostic's tokens | their own databases |

Runtime data (sessions, memories, knowledge, component configs) stays in the AgentOS runtimes. Agnostic reads it on
behalf of the signed-in person and doesn't copy it, apart from short-lived caches and the audit log.

## Data flows

**Gateway mode (default).** The browser talks only to Agnostic, on one origin, with an `HttpOnly` session cookie
and a CSRF token. For a call to a runtime the gateway:

1. resolves the route's required scopes from its route policy table;
2. checks the person's effective scopes on that instance (and explains a denial);
3. applies service-account restrictions, rate limits and the circuit breaker;
4. signs a JWT for exactly the person's runtime scopes (cached until shortly before expiry);
5. forwards the request and streams the response back; audits writes, denials and sampled reads.

AgentOS verifies the JWT (RS256, audience = its own id, issuer = Agnostic's URL) and enforces the scopes itself, so a
gateway bug can't grant more than the token carries.

**Direct mode (opt-in per instance).** The browser fetches a short-lived token (`POST
/api/v1/instances/{id}/token`, audited, rate-limited) and calls the runtime over TLS with CORS. The token carries the
same scopes; AgentOS's decision log is ingested into the audit log.

**Control-plane calls.** Some features call runtimes as the control plane (Home aggregates, the approvals inbox,
health checks) with a system token, after checking the person's scope in Agnostic. Typed actions that need admin
rights under user isolation (deciding an approval, testing a draft) use **delegated elevation**: a single-use,
60-second admin token whose subject is still the person, audited as `gateway.elevated`, and switchable off per
instance.

## Identity and authorization

- **Authentication**: local accounts (argon2id, 12+ characters, lockout after 5 failures), OIDC (PKCE, nonce,
  state), SAML 2.0 (signed responses, replay protection), GitHub; MFA (TOTP, recovery codes) with an org policy;
  SSO enforcement with one break-glass Owner; SCIM 2.0 deprovisioning ends sessions and removes bindings at once.
- **Sessions**: opaque random cookies, stored as SHA-256 hashes; 12-hour sliding and 7-day absolute lifetime;
  revocable per browser.
- **Invitations**: emailed or created as a link to share, shown once (only the token's hash is stored), single use,
  expiring after 7 days; a new link replaces the old one; every step is audited. A forwarded link proves nothing, so
  under enforced SSO (or with local login off) accepting with a password is refused and the invitee joins through
  the IdP, matched by verified email.
- **Two scope tiers**: control-plane scopes (`org:*`, `os:*`, `audit:*`, `settings:*`, `studio:*`,
  `org:system:*`…) carried by org roles (Owner, Administrator, Member); runtime scopes (agno's `agents:run`,
  `sessions:read`…) carried by access roles bound to people, groups or service accounts per instance or org-wide.
  Effective scopes are cached and invalidated on every change, so a role change reaches runtimes within a minute.
- **Runtime tokens**: RS256 with a 3072-bit key per instance, `kid` = RFC 7638 thumbprint, 5-minute lifetime by
  default, `jti` per token; rotation is two-step through a JWKS document.
- **Service accounts**: scoped gateway tokens (`agn_pat_…`, stored as peppered hashes) and native per-instance JWTs,
  with expiry; privileged ones need a recent sign-in to create.

## Cryptography

| Use | Algorithm |
|---|---|
| Secrets at rest | envelope encryption: a random AES-256-GCM data key per value, wrapped with AES-256-GCM by the master key (the key id as associated data) |
| Master key | 32 random bytes; local, or wrapped by HashiCorp Vault / OpenBao Transit, AWS KMS, Azure Key Vault (RSA-OAEP-256) or Google Cloud KMS, unwrapped once per process |
| Key rotation | a key ring opens values sealed with any configured key; `agnostic secrets rotate` re-seals |
| Runtime tokens | RS256 (RSA 3072) |
| Passwords | argon2id |
| Session cookies, invitation and reset tokens | 256-bit random, stored as SHA-256 |
| Service-account tokens | stored as SHA-256 of a pepper (derived from the master key, or configured) and the token |
| Audit hash chain | SHA-256 over the previous hash and the event's canonical JSON |
| Audit archives | SHA-256 per archived month, recorded in a manifest and in the database |
| Webhooks (outbound) | HMAC-SHA256 signatures |
| Transport | TLS to every endpoint; mutual TLS to runtimes when configured |

Private keys of instances never leave the API process; only signed tokens do.

## Threat model summary

| Asset | Threat | Controls |
|---|---|---|
| Runtime data (sessions, memories, knowledge) | a person reads more than they may | AgentOS enforces token scopes; per-user isolation; scopes checked twice in gateway mode; audit of denials |
| Instance signing keys | theft, misuse | sealed at rest, never returned, used only in process; 5-minute tokens; two-step rotation |
| The master key | loss, theft | outside the database; KMS providers; key ring and rotation; backup procedure |
| Sessions and accounts | credential stuffing, session theft, CSRF | lockout and rate limits, MFA, SSO enforcement, `HttpOnly`/`Secure`/`SameSite` cookies, CSRF tokens, re-authentication for sensitive changes |
| The web app | XSS, clickjacking | React rendering only, no HTML sinks, strict CSP with Trusted Types, `frame-ancestors 'none'` |
| Studio publish path | an unreviewed change reaches production | drafts vs published versions, eval gates with audited overrides, git pull requests, promotion checks |
| Audit log | tampering, loss | append-only writes, hash chain, verified archives with Object Lock, SIEM streaming at least once |
| The assistant | prompt injection leading to actions | read-only tools executed as the asking person; answers cite their sources; off unless configured |
| Code sources | malicious code executed | repository code is parsed, never executed, by isolated worker processes with timeouts and size limits |
| Supply chain | a compromised dependency | exact pins, audits, SBOM, signed images, license policy |

Detailed review status: [Threat model review](threat-model-review.md).

## What leaves the network

Nothing by default. Agnostic makes no update checks, sends no telemetry, loads no fonts or scripts from CDNs, and
calls a model provider only when an administrator configures one for AI features. Every outbound connection goes to
a configured endpoint (database, cache, object storage, SMTP, OTLP, IdP, SIEM, git hosts, KMS, runtimes). A CI job
runs the image on a network without egress to keep it that way.

## Supply chain

- Dependencies are pinned to exact versions in lockfiles (Python and npm) and updated by reviewed pull requests with
  a minimum release age; base images are pinned by digest.
- Every change runs `pip-audit`, `yarn npm audit`, gitleaks, and a license check against the policy (BSD-3-Clause
  project; permissive dependencies; reviewed weak-copyleft libraries used unmodified; strong copyleft refused).
- The image is scanned with trivy, gets a CycloneDX SBOM (checked against the same license policy), and release
  images are signed with cosign keyless signing, with the SBOM and SLSA build provenance attested.
- The image is non-root, works with a read-only root filesystem and contains only Agnostic and its dependencies.

## Reporting vulnerabilities

See `SECURITY.md` in the repository: report privately through a GitHub security advisory.
