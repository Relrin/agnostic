# Release checklist

Copy this list into the release pull request (the one release-please opens) and tick every item before merging it.
Record links to the runs and documents.

## CI

- [ ] `ci` is green on the release commit, including:
  - [ ] backend lint, types, unit and integration (Postgres 18, Redis 8)
  - [ ] runtime and bridge (Python 3.13)
  - [ ] frontend lint, types, unit; Storybook with axe; Playwright e2e
  - [ ] `e2e-csp`: the production build under the production CSP and Trusted Types
  - [ ] `image`: build, smoke test (read-only, non-root), trivy with no fixable HIGH or CRITICAL findings, SBOM and
        its license check, the Compose example validates
  - [ ] `helm`: lint, kubeconform on Kubernetes 1.30, the schema refuses secrets in `config`
  - [ ] API client drift, licenses, security audits and gitleaks
- [ ] `contract` (live AgentOS) is green for the supported agno versions.
- [ ] `perf` (nightly) is within budget on the release commit: gateway overhead p95 under 25 ms, 1,000 streams per
      API replica.
- [ ] `air-gapped (egress denied)` is green.

## Drills

- [ ] **Upgrade drill**: `upgrade & restore drills › upgrade-drill` passes from every milestone in
      `deploy/upgrade-milestones.txt`. Add the previous release's commit to that file.
- [ ] **Restore drill**: `upgrade & restore drills › restore-drill` passes, and the production-like drill in the
      staging environment was run ([runbook](../guides/runbooks/restore-drill.md)). Date and duration:
- [ ] `agnostic db upgrade --check` against an anonymized production-sized copy: no failures, slowest migration:

## Security

- [ ] No open critical or high findings from the penetration test ([scope](../guides/security/pentest-scope.md)), or
      each one accepted in writing.
- [ ] The threat model review is current ([review](../guides/security/threat-model-review.md)).
- [ ] The ASVS checklist is current ([checklist](../guides/security/asvs-l2-checklist.md)).

## Accessibility

- [ ] Accessibility sign-off for the release: automated checks green, the manual screen-reader pass done
      ([accessibility](../guides/accessibility.md)). Signed off by:

## Fresh install

- [ ] A person who hasn't installed Agnostic before follows [Install Agnostic](../guides/admin/install.md) from
      nothing to chatting with an agent, signed in through an IdP, in under 30 minutes. Name, date, time taken,
      notes on anything unclear (and the doc fixes):

## Artifacts (after the tag)

- [ ] The `release` workflow published the image for amd64 and arm64.
- [ ] The image signature and attestations verify:

  ```bash
  cosign verify ghcr.io/relrin/agnostic@sha256:<digest> \
    --certificate-identity-regexp '^https://github.com/Relrin/agnostic/\.github/workflows/release\.yml@' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  cosign verify-attestation --type cyclonedx ghcr.io/relrin/agnostic@sha256:<digest> \
    --certificate-identity-regexp '^https://github.com/Relrin/agnostic/' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  gh attestation verify oci://ghcr.io/relrin/agnostic@sha256:<digest> --owner Relrin
  ```

- [ ] `python3 scripts/check_sbom_licenses.py sbom.cdx.json` passes on the release SBOM.
- [ ] The Helm chart is in the OCI registry and its signature verifies.
- [ ] The air-gapped kit is attached to the release; `sha256sum -c SHA256SUMS` passes after downloading it.
- [ ] `agnostic-bridge` is published (PyPI or the customer index) when its version changed; `pip install
      agnostic-bridge==<version>` works in a clean environment.
- [ ] The runtime template is exported (`scripts/export_runtime_template.sh <version>`) and pushed.
- [ ] Release notes in `docs/release-notes/<version>.md`, linked from the GitHub release.
