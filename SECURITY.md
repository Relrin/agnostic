# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, never in a public issue or pull request:
open a [private security advisory](https://github.com/Relrin/agnostic/security/advisories/new) on this repository.

Include what you found, the affected version or commit, steps to reproduce, and the impact you expect. Proofs of
concept are welcome; please don't access data that isn't yours or degrade other people's installations.

## What to expect

| When | What |
|---|---|
| within 3 working days | we confirm we received the report |
| within 10 working days | a first assessment: severity, affected versions, and whether we can reproduce it |
| before the fix is public | a fix or mitigation, a release, and an advisory with a CVE when it applies; we agree a disclosure date with you |

We credit reporters in the advisory unless you ask us not to.

## Supported versions

| Version | Security fixes |
|---|---|
| 1.0.x | yes |
| pre-1.0 (0.x) | no: upgrade to 1.0 |

The latest patch release of each supported minor gets fixes. `agnostic-bridge` follows the same policy for its own
versions.

## Scope

This repository's code and the artifacts built from it: the `agnostic` image, the Helm chart, the Compose example,
the air-gapped kit, `agnostic-bridge` and the runtime template. Vulnerabilities in Agno itself go to the Agno
project; vulnerabilities in your own endpoints (database, cache, IdP) go to their vendors.

How Agnostic is secured, and how to harden an installation, is in the guides: `docs/guides/security/whitepaper.md`
and `docs/guides/admin/hardening.md`.
