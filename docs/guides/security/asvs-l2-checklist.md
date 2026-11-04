# ASVS level 2 checklist

How Agnostic maps to the OWASP Application Security Verification Standard 4.0.3, level 2, chapter by chapter.
Status:

- **Implemented**: built in and covered by tests.
- **Customer**: depends on how the installation is run; the guide says how.
- **Pentest**: implemented, to be confirmed by the external penetration test before sign-off.

| Chapter | How Agnostic addresses it | Status |
|---|---|---|
| V1 Architecture, design and threat modeling | modular monolith with enforced module boundaries; threat model per asset ([whitepaper](whitepaper.md)); every external dependency is a configured endpoint; authorization enforced by AgentOS from scoped tokens, not only by the gateway | Implemented; threat model review pending ([review](threat-model-review.md)) |
| V2 Authentication | argon2id, 12+ characters, no composition rules; lockout (5 per email / 15 min) and per-IP limits; TOTP MFA with recovery codes and an org policy; OIDC with PKCE and nonce; SAML with signature, audience, recipient and replay checks; SSO enforcement with a break-glass account | Implemented; Pentest for SAML edge cases |
| V3 Session management | opaque 256-bit cookies stored hashed; `HttpOnly`, `Secure`, `SameSite=Lax`; sliding and absolute lifetimes; revocation per browser; every session ends on deprovisioning and on a password reset | Implemented |
| V4 Access control | deny by default per route policy; scopes checked server side for every call and again by AgentOS; least privilege roles; re-authentication for sensitive changes; CSRF tokens on unsafe requests | Implemented; Pentest (IDOR across instances and orgs) |
| V5 Validation, sanitization and encoding | typed request models (pydantic) with limits; parameterized SQL only; no HTML sinks in the web app; code from repositories parsed, never executed, in isolated workers | Implemented |
| V6 Stored cryptography | AES-256-GCM envelope encryption; KMS providers; key ring and rotation; random from the OS CSPRNG; no custom crypto primitives | Implemented; Customer (master key custody) |
| V7 Error handling and logging | RFC 9457 problem responses without stack traces; request ids; JSON logs without secrets; audit log of every change and denial with a hash chain and SIEM streaming | Implemented |
| V8 Data protection | secrets never returned by the API; `Cache-Control: no-store` on tokens; data-subject requests for context data; retention and archive settings | Implemented; Customer (retention choices) |
| V9 Communication | TLS to every endpoint, verification on by default for HTTPS; PostgreSQL `sslmode=verify-full` available (the default is `prefer`); mutual TLS to runtimes; HSTS | Customer (TLS at the proxy and endpoints); Implemented in the product |
| V10 Malicious code | dependency pinning, audits, SBOM, signed images; no dynamic code execution; the assistant's tools are read-only | Implemented |
| V11 Business logic | rate limits on sign-in, gateway buckets and token issue; approvals and publish gates audited; idempotent approval decisions | Implemented; Pentest |
| V12 Files and resources | upload size limits and streaming; downloads from runtimes passed through without parsing; no server-side URL fetching from user input except configured endpoints | Implemented; Pentest (SSRF through instance URLs: admins only) |
| V13 API and web services | one versioned API (`/api/v1`) with OpenAPI; CSRF and same-origin; CORS off unless configured; schema-validated bodies | Implemented |
| V14 Configuration | non-root, read-only image; pinned digests; security headers with CSP and Trusted Types; production refuses to start without a master key; chart schema keeps secrets out of plain values | Implemented; Customer (deployment hardening, [Hardening](../admin/hardening.md)) |

Open items before sign-off: the external penetration test ([scope](pentest-scope.md)), the threat model review, and a
documented decision on `style-src 'unsafe-inline'` (needed by the code editor and charts).
