# Install Agnostic

Agnostic runs as one image, `agnostic`, that you build from the release tag ([Build the images](build-images.md)).
It has three commands: `api` (the HTTP API, which also serves the web app),
`worker` (background jobs and schedules) and `migrate` (database migrations). Everything it depends on is an
endpoint you already run: PostgreSQL, a Redis-compatible cache, and optionally object storage, SMTP, an OTLP
collector, your identity provider and your AgentOS runtimes. Agnostic never installs or operates them.

This guide gets you from nothing to chatting with an agent, signed in through your IdP, in about 30 minutes.

## Requirements

| Endpoint | Supported | Needed for |
|---|---|---|
| PostgreSQL | 17 or 18, with the `citext` and `pg_trgm` extensions available | everything (the only stateful dependency that matters) |
| Cache | Redis 7.4+ or 8, Valkey 8+, DragonflyDB 1.x; TLS (`rediss://`) and Sentinel supported | sessions, caches, rate limits, realtime |
| Object storage | any S3-compatible service (AWS S3, MinIO, Ceph, SeaweedFS, R2…) | the audit archive (optional) |
| SMTP | STARTTLS on 587 or implicit TLS on 465 | invitation and password-reset emails (without it, invitations are links you share and reset emails go to the log) |
| OTLP/HTTP collector | OpenTelemetry Collector or compatible | traces of the control plane itself (optional) |
| Identity provider | OIDC (Okta, Entra ID, Google, Keycloak, GitLab…), SAML 2.0, GitHub | SSO (local accounts work without one) |
| AgentOS | Agno AgentOS 3.1.x | the runtimes you manage (see [Bridge and runtime](../bridge-and-runtime.md)) |
| Docker | Docker Engine 23+ (BuildKit) and Docker Compose v2 | building and running the image |

Size for a start: two API replicas (0.25 CPU, 384 MiB each) and two workers (0.1 CPU, 256 MiB). Add API replicas as
concurrent chat streams grow.

## Before you start

Prepare these values; every setting is an `AGNOSTIC_*` environment variable (the full list is in the configuration
reference shipped with the repository, `docs/reference/configuration.md`).

| Setting | Example |
|---|---|
| `AGNOSTIC_HTTP__PUBLIC_URL` | `https://agnostic.example.com`, the URL people open (behind your reverse proxy) |
| `AGNOSTIC_DATABASE__URL` | `postgresql://agnostic:…@db.example.com:5432/agnostic` |
| `AGNOSTIC_DATABASE__SSLMODE` | `verify-full` (with `AGNOSTIC_DATABASE__TLS__CA_FILE` for a private CA) |
| `AGNOSTIC_REDIS__URL` | `rediss://:…@cache.example.com:6380/0` |
| `AGNOSTIC_SECRETS__MASTER_KEY` | from `agnostic secrets generate-key`; see [Key management](key-management.md) |
| `AGNOSTIC_SMTP__URL`, `AGNOSTIC_SMTP__SENDER` | `smtp://user:…@smtp.example.com:587`, `Agnostic <agnostic@example.com>` |
| `AGNOSTIC_TLS__CA_FILE` | your organization's CA, if runtimes or IdPs use certificates from it |

Build the image first ([Build the images](build-images.md)); the commands below use the local tag
`agnostic:0.4.1`.

Generate the master key once and store a copy somewhere safe (a password manager or your secret store). Without it,
every stored secret is lost:

```bash
docker run --rm agnostic:0.4.1 secrets generate-key
```

### Pre-flight checklist

- [ ] The database exists, the Agnostic user owns it, and `citext` and `pg_trgm` can be created (managed services
      may need an allow-list entry: see [Managed services](managed-services.md)).
- [ ] The cache answers and allows the commands Agnostic uses (`config check --connect` lists any that are refused).
- [ ] The public URL resolves to your reverse proxy, with a TLS certificate.
- [ ] Your reverse proxy doesn't buffer responses and allows reads of at least an hour (chat streams are server-sent
      events).
- [ ] The master key is generated and backed up.
- [ ] From where the API will run, the AgentOS runtimes and your IdP are reachable.

`agnostic config check --connect` probes every configured endpoint (database version and extensions, migrations,
cache commands, the master key, SMTP, OTLP, sign-in providers, the audit archive bucket and every connected runtime)
and exits with 1 when any of them fails. Run it before the first start and after every change.

## Install with Docker Compose

`deploy/compose/` runs only the `agnostic` image: `migrate` once, then `api` and `worker`.

```bash
cd deploy/compose
cp .env.example .env            # set AGNOSTIC_IMAGE, the endpoints and the master key
docker compose run --rm api config check --connect
docker compose up -d
```

The containers run with a read-only root filesystem, a tmpfs at `/tmp` and a volume at `/var/lib/agnostic` (git
mirrors of code sources). The API listens on port 8000 in plain HTTP: put your TLS-terminating reverse proxy in
front of it. `AGNOSTIC_IMAGE` picks the image: the local tag (`agnostic:0.4.1`) or its reference in your registry.

## Create the first Owner

```bash
docker compose run --rm api bootstrap --org-name "Northwind Labs"
```

This prints a one-time link, valid for 24 hours, where the first Owner creates their account. With
`--owner-email` it creates the Owner directly and asks for the password (`--password-stdin` reads it from stdin).

## From install to chat

1. **Sign in** with the link from bootstrap.
2. **Connect your IdP** in *Organization › Authentication* (OIDC or SAML) and turn on JIT provisioning for your
   domain, or invite people (*People & groups › Invite people*, by email or as a link to share). Sign out and back
   in through the IdP. See [Sign-in, SSO and SCIM](sso-and-scim.md).
3. **Connect an instance**: *Instances › Connect* asks for the AgentOS URL, discovers it, and shows the public key to
   add to the runtime (`JWT_VERIFICATION_KEY`). Restart the runtime, then *Test connection*. See
   [Instances and keys](instances-and-keys.md).
4. **Chat**: open the instance, pick an agent in *Chat* and send a message.

If a step fails, *Test connection* explains which check failed and how to fix it, and the
[instance unreachable runbook](../runbooks/instance-unreachable.md) covers the rest.
