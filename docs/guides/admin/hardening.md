# Hardening

A checklist for production installs. Most of it is on by default; the rest depends on your environment.

## Browser security

Every response carries:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`, scripts only from the app's origin (plus `'wasm-unsafe-eval'` for syntax highlighting), frames and `blob:` media only from the app's origin (artefact previews, each sandboxed by its own policy), no plugins, `base-uri 'none'`, `connect-src` limited to the app and direct-mode runtimes |
| Trusted Types | `require-trusted-types-for 'script'`: the web app has no HTML sinks of its own; its `default` policy refuses HTML strings (except two constant style rules of the UI library) and allows script URLs only from the app's origin |
| `Strict-Transport-Security` | `max-age=31536000` when the public URL is `https://` |
| `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy` | `nosniff`, `DENY`, `no-referrer`, camera/microphone/geolocation/payment/usb off, `same-origin-allow-popups`, `same-origin` |

Styles allow `'unsafe-inline'` because the code editor and charts set inline style attributes.

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_HTTP__CSP_REPORT_ONLY` | `false` | send the policy as report-only while trying a new setup |
| `AGNOSTIC_HTTP__CSP_EXTRA_CONNECT` | — | extra `connect-src` origins, comma-separated |
| `AGNOSTIC_HTTP__HSTS_MAX_AGE` | `31536000` | `0` leaves HSTS to your proxy |

Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure` behind HTTPS; unsafe requests need the CSRF token.

## TLS everywhere

| Endpoint | How |
|---|---|
| Browsers | TLS at your reverse proxy or ingress |
| PostgreSQL | `AGNOSTIC_DATABASE__SSLMODE=verify-full`, `AGNOSTIC_DATABASE__TLS__CA_FILE` |
| Cache | `rediss://` URLs, `AGNOSTIC_REDIS__TLS__CA_FILE` (client certificates: `__CERT_FILE`, `__KEY_FILE`) |
| SMTP | STARTTLS or `smtps://`, `AGNOSTIC_SMTP__TLS__*` |
| OTLP | `https://` endpoint, `AGNOSTIC_OTEL__TLS__*` |
| Runtimes | verified TLS, per-instance CA bundles, client certificates: [Instances and keys](instances-and-keys.md) |
| Everything outbound | `AGNOSTIC_TLS__CA_FILE` adds your organization's CA |

## The container

The image runs as uid 10001, works with a read-only root filesystem (writes go to `/tmp` and `/var/lib/agnostic`)
and needs no Linux capabilities. The Compose file runs it with `read_only`, `cap_drop: [ALL]` and
`no-new-privileges`. Keep those settings.

## Network

- Limit the containers' egress with your firewall to the endpoints the control plane calls (database, cache,
  object storage, IdP, SMTP, SIEM, git hosts, KMS) and your runtimes.
- Metrics are served on port 9464 of the API and the workers, which the Compose file doesn't publish. That port has
  no authentication: if you publish it, only allow Prometheus to reach it. The API's main port answers `/metrics`
  only when `AGNOSTIC_METRICS__TOKEN` is set, and then only with that bearer token.
- Keep runtimes in gateway mode unless you need [direct mode](direct-mode.md).

## Secrets

- Database and cache URLs and the master key belong in `.env` (readable only by the account that deploys) or
  your secret store, never in the image, the Compose file or the repository.
- Use a KMS provider for the master key where you have one: [Key management](key-management.md). Rotate it yearly.
- Sealed secrets are never returned by the API; forms show "set" or "not set".

## Identity

- Enforce SSO and keep one break-glass Owner (*Organization › Authentication*).
- Set the MFA policy for password sign-ins to `required_admins` at least.
- Use groups from your IdP and bind roles to groups, not people.
- Review service accounts and their token expiry; privileged ones need a recent sign-in to create.

## Audit

- Turn on the hash chain (*Organization › Audit retention & archive*) and verify it regularly: [Audit integrity](audit-integrity.md).
- Stream the audit log to your SIEM, and archive to a bucket with Object Lock in compliance mode.

## Build and pin the image

No images are published, so the image you run is one you built ([Build the images](build-images.md)):

- Build from a release tag on a build host you control, scan it (trivy) and keep its SBOM (syft) as described there.
- Push it to your own registry and deploy by digest (`AGNOSTIC_IMAGE=registry.internal/agnostic@sha256:<digest>`), so
  a re-pushed tag can't change what runs.
- Sign it with your own key (`cosign sign --key`) and have the cluster refuse unsigned images with an admission
  controller (Sigstore policy-controller, Kyverno or Connaisseur) configured with your `cosign.pub`.
