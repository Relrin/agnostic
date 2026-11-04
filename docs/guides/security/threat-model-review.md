# Threat model review

The threat model is reviewed before every major release and after any change to authentication, authorization,
cryptography or the data path. This page has the template and the current review.

## Template

For each asset in the [whitepaper's threat model](whitepaper.md#threat-model-summary):

| Field | Content |
|---|---|
| Asset | what is protected |
| Entry points | how it can be reached (routes, jobs, CLI) |
| Threats | STRIDE: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege |
| Controls | what prevents or detects each threat, with the code or test that shows it |
| Residual risk | what remains, and who accepts it |
| Actions | changes needed, with an owner |

Reviewers: one engineer who built the area, one who didn't, and the security contact.

## Current review (1.0)

| Asset | Changes since the last review | Residual risk | Open actions |
|---|---|---|---|
| Runtime data | direct mode lets browsers call runtimes | direct mode bypasses gateway rate limits and explanations; the runtime must have TLS and CORS limited to Agnostic's origin | document per-instance opt-in (done); pentest the token endpoint |
| Instance signing keys | client certificate keys sealed the same way | a process memory dump exposes opened keys | none; covered by host security |
| The master key | KMS providers, key ring, rotation tooling | a compromised KMS identity can unwrap the key | use KMS key policies requiring the encryption context; audit KMS usage |
| Sessions and accounts | no change | SAML parser surface | pentest SAML edge cases |
| The web app | CSP with Trusted Types; HTML rendering of highlighted code replaced by React elements | `style-src 'unsafe-inline'` permits CSS injection if an injection point exists | evaluate nonce-based styles for the code editor |
| Metrics | new `/metrics` endpoint | exposes route names and counts | served on a port of its own (9464) that ingresses don't route; the main port answers only with `AGNOSTIC_METRICS__TOKEN`; restrict 9464 to Prometheus ([Hardening](../admin/hardening.md)) |
| Audit log | archive verification and restore checks | an attacker with database write access can rewrite unchained history before the chain is turned on | turn the hash chain on by default in a future release |
| Supply chain | signed images, SBOM, provenance | signatures only help if verified at deploy time | document admission-controller enforcement (in [Hardening](../admin/hardening.md)) |

Sign-off: pending the external penetration test.
