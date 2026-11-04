# Guides

Guides for administrators and operators. They ship with every installation and the web app shows them under
*Help*, so they work without internet access.

## Administration

| Guide | For |
|---|---|
| [Install Agnostic](admin/install.md) | requirements, the pre-flight checklist, Compose and Helm, the first Owner |
| [Air-gapped installations](admin/air-gapped.md) | the offline kit, mirroring the image and chart, no outbound calls |
| [Sign-in, SSO and SCIM](admin/sso-and-scim.md) | local accounts, invitations, OIDC and SAML providers, directory sync |
| [Instances and keys](admin/instances-and-keys.md) | connecting AgentOS runtimes, JWT keys, CA bundles, client certificates |
| [Direct mode](admin/direct-mode.md) | browsers calling a runtime themselves |
| [Key management](admin/key-management.md) | the master key, KMS and Vault providers, rotation |
| [Backups and disaster recovery](admin/backups-and-dr.md) | what to back up, RPO and RTO, the DR runbook |
| [Upgrades](admin/upgrades.md) | rolling upgrades, migration checks, rollback, pre-release databases |
| [Hardening](admin/hardening.md) | security headers, TLS, network policies, image signatures |
| [Managed services](admin/managed-services.md) | RDS, Cloud SQL, Azure, ElastiCache, Memorystore, S3-compatible storage |
| [Observability](admin/observability.md) | metrics, alerts, traces, logs, health endpoints |
| [The System page](admin/system-page.md) | versions, endpoint checks, job queues, failed jobs |
| [Audit integrity](admin/audit-integrity.md) | the hash chain, verifying and restoring archived months |

## Building and operating

| Guide | For |
|---|---|
| [Builder guide](builder.md) | Studio: agents, teams, workflows, versions, publishing, code sources |
| [Operator guide](operator.md) | chat, sessions, approvals, schedules, the queue, traces, context |
| [Bridge and runtime](bridge-and-runtime.md) | `agnostic-bridge` and the reference AgentOS template |
| [Accessibility](accessibility.md) | keyboard and screen-reader support, the audit checklist |

## Runbooks

| Runbook | When |
|---|---|
| [Instance unreachable](runbooks/instance-unreachable.md) | a runtime is down, slow or rejects the control plane |
| [Key rotation](runbooks/key-rotation.md) | rotating an instance's JWT keys or the master key |
| [SIEM backlog](runbooks/siem-backlog.md) | a SIEM destination is failing and events pile up |
| [Failed jobs](runbooks/job-dead-letters.md) | background jobs failed and wait on the System page |
| [Restore drill](runbooks/restore-drill.md) | proving a backup restores |

## Security

| Document | For |
|---|---|
| [Security whitepaper](security/whitepaper.md) | architecture, data flows, cryptography, threat model |
| [ASVS level 2 checklist](security/asvs-l2-checklist.md) | how Agnostic maps to OWASP ASVS 4.0.3 level 2 |
| [Penetration test scope](security/pentest-scope.md) | scope and rules of engagement for an external test |
| [Threat model review](security/threat-model-review.md) | the review template and the current review |
