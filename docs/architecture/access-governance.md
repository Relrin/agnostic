# Access governance

The effective-scope engine from [identity, access and the gateway](identity-access-gateway.md), fed by groups,
editable roles, service accounts and temporary grants, with identity providers keeping people and groups in sync
and an audit log that can be searched, exported, streamed and archived.

![Access governance: IdP sync into groups, roles, bindings and temporary access, service accounts, effective scopes, gateway, audit, SIEM and archive](images/access-governance.svg)

## Modules

| Module | Owns | Tables |
|---|---|---|
| `directory` | manual and IdP groups, SCIM 2.0 server, mapping rules, Google Workspace sync, deprovisioning | `dir_*` |
| `access` | versioned roles; bindings for people, groups and service accounts; temporary access; `access.expire_bindings` | adds `access_role_versions`, `access_temp_grant_requests` |
| `identity` | OIDC and SAML 2.0 providers in the database, auth policy (enforce SSO, break-glass, session lifetime, MFA), TOTP and WebAuthn, step-up | adds `identity_login_providers`, `identity_auth_policy` |
| `service_accounts` | machine identities, native AgentOS tokens, gateway tokens with rotation | `sa_*` |
| `audit` | saved views, export, hash chain, retention and S3 archive, SIEM sinks, AgentOS ingestion | adds `audit_saved_views`, `audit_exports`, `audit_policy`, `audit_archives`, `audit_sinks`, `audit_sink_cursors`, `audit_ingest_cursors` |
| `gateway` | service-account principals; `gateway.ingest_authz` | — |

Upward calls use ports ([module system](module-system.md#talking-across-modules)).

## Effective access and roles

A person's scopes are their own bindings, their groups' bindings and their org role's implicit access; a service
account has only its own. Grants remember their group ("Granted by Operator via Support AI"). Changes to bindings,
roles, groups or membership bump the access generation and apply on the next request.

Built-in roles (Instance admin, Operator, Builder, Viewer, Auditor) are seeded once, then editable ("Reset" restores
them). A role is a permission matrix checked against the scope catalog, an optional per-component run scope, and the
instances it may be bound on. Each save is a version and a `roles.update` event; `POST
/api/v1/access/roles/{id}/preview` shows the diff and who is affected. A bound role can't be deleted.

## Groups and identity providers

| IdP | People | Groups |
|---|---|---|
| Okta, Entra ID | SCIM `/scim/v2/Users` | SCIM `/scim/v2/Groups` |
| Keycloak or any IdP with a groups claim | OIDC/SAML, JIT or invitation | claim or SAML attribute at sign-in |
| Google Workspace | OIDC | Directory API sync every 15 minutes |
| none | local accounts, invitations | manual groups |

Mapping rules carry IdP groups into manual groups. Deprovisioning (SCIM `active=false` or DELETE, a suspended Google
user) ends sessions and removes bindings and group memberships (with the "remove" behaviour, the org membership too); the
only active Owner can't be deprovisioned.

## Sign-in policy

SAML is a small service provider (signed Response or Assertion via `signxml`; audience, recipient, validity,
`InResponseTo`, replay). **Enforce SSO** turns passwords off, invitation acceptance included, except for one
break-glass Owner whose sign-ins are audited and announced. The MFA policy (`optional`, `required_local`,
`required_admins`) covers password sign-ins. Sensitive changes need a recent authentication (`403
reauth_required`).

## Service accounts

| Token | Validated by | Rotation |
|---|---|---|
| native `agno_pat_…`, per instance | AgentOS | revoke and recreate |
| gateway `agn_pat_…` | Agnostic (peppered hash); the gateway mints a JWT per request | new token, old one valid 24 h |

Gateway JWTs carry `sub = svc_<name>` (AgentOS reserves `sa:`) and `agnostic.principal = "sa:<name>"`; `user_id` is
stripped unless the account forwards it. Service accounts can't resolve approvals. Privileged scopes need
confirmation and recent authentication, and notify Owners.

## Temporary access

Members request a role or scopes on an instance for some hours; Owners, Administrators and owners of a group that
already has that access approve. Approval creates an expiring binding (max `temporary_access_max_hours`, 168).

## Audit log

- Filters by actor, action, decision, instance, date and source (Agnostic or AgentOS); saved views; denials keep the
  explanation the person saw.
- Export as CSV or JSONL: streamed up to 10 000 rows, otherwise a background job.
- SIEM: HTTPS webhooks (`X-Agnostic-Signature: t=…,v1=…`), syslog (RFC 5424 over TCP/TLS), OTLP/HTTP logs; JSON,
  OCSF or CEF; at least once via a per-sink cursor ([SIEM and archive](../how-to/audit-siem-and-archive.md)).
- Retention: 400 days in PostgreSQL; with the archive on, each expiring month is written to S3-compatible storage
  (JSONL.zst + manifest), verified, then dropped; "Restore for search" brings a month back for 7 days.
- Optional hash chain, checked by `agnostic audit verify`.
- AgentOS ingestion of `/authz/decisions` and `/authz/audit`, so direct-mode and native-token traffic appears with
  `source = agentos`.
