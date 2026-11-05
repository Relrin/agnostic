# Compatibility

What each Agnostic release works with. The "CI" column is what `.github/workflows/ci.yml` and `contract.yml` test on
every change; the rest is supported and checked by `agnostic config check --connect`.

## Agnostic × AgentOS × bridge

| Agnostic | Agno / AgentOS | agnostic-bridge | Notes |
|---|---|---|---|
| 1.0.x | 3.1.x (3.1.12+); CI runs the contract suite against the pinned 3.1.12 | 1.0.x | Studio needs a sync `PostgresDb` on the runtime; per-user permissions need `authorization=True` with the control plane's public key |

- The bridge is optional. Without it, the features that need its routes (component validation, file provenance,
  worker details, the event feed, code introspection, CEL preview) show as unavailable for that instance.
- A new Agno minor needs a new bridge version (its `agno` range is the tested minor) and a contract run.
- The control plane warns on an instance whose Agno minor changed ("version drift") and keeps working with the
  routes it knows.

## Endpoints

| Endpoint | Supported | CI |
|---|---|---|
| PostgreSQL | 17, 18 (`citext` and `pg_trgm` available) | 18 |
| Redis-compatible cache | Redis 7.4+, 8; Valkey 8+; DragonflyDB 1.x | Redis 8 (Redis 7.4, Valkey and DragonflyDB: `config check --connect` probes the commands used) |
| Object storage (audit archive) | S3-compatible with path-style URLs (AWS S3, MinIO, Ceph RGW, SeaweedFS, R2, Wasabi); Object Lock optional | SeaweedFS (dev stack), fake S3 (tests) |
| SMTP | STARTTLS or implicit TLS | captured mailer (tests) |
| OTLP | OTLP/HTTP traces | — |
| Identity providers | OIDC (Okta, Microsoft Entra ID, Keycloak, Google, GitLab, generic), GitHub OAuth, SAML 2.0, SCIM 2.0 | Keycloak (dev stack), fake IdPs (tests) |
| Master-key providers | local, HashiCorp Vault / OpenBao Transit, AWS KMS, Azure Key Vault / Managed HSM, Google Cloud KMS | OpenBao (dev stack), recorded fakes (tests) |
| Git hosts (code sources) | GitHub (App or token), GitLab, Gitea, Forgejo; local folders | Gitea (dev stack), recorded GitHub/GitLab fixtures |

Managed services and their quirks (extension allow-lists, TLS bundles, disabled cache commands):
[managed services](../guides/admin/managed-services.md).

## Platforms

| Artifact | Platforms |
|---|---|
| `agnostic` image | linux/amd64, linux/arm64; any OCI runtime; read-only root filesystem, uid 10001 |
| Compose example | Docker Compose v2 |
| agnostic-bridge | Python 3.10–3.13, wherever the AgentOS runs (CI tests 3.13) |
| Web app | current Chrome, Edge, Firefox and Safari (Trusted Types are enforced where the browser supports them) |
