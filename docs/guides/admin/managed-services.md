# Managed services

Agnostic works with managed PostgreSQL, Redis-compatible caches and object storage. This page lists what differs
between providers. `agnostic config check --connect` tells you when something is missing.

## PostgreSQL

Agnostic needs PostgreSQL 17 or 18 and creates the `citext` and `pg_trgm` extensions in its first migration. Its
tables live in the `agnostic` schema, jobs in the `procrastinate` schema; the database user must own the database or
be allowed to create schemas in it.

| Service | Extensions | TLS |
|---|---|---|
| AWS RDS / Aurora PostgreSQL | both are supported; the migrating user needs `rds_superuser` or a database it owns | download the RDS CA bundle; `AGNOSTIC_DATABASE__SSLMODE=verify-full`, `AGNOSTIC_DATABASE__TLS__CA_FILE=/etc/agnostic/rds/global-bundle.pem` |
| Google Cloud SQL | both are supported | the instance's server CA; or the Cloud SQL Auth Proxy as a sidecar (then `sslmode=disable` to the local proxy) |
| Azure Database for PostgreSQL (Flexible Server) | allow-list them first: server parameter `azure.extensions` = `CITEXT,PG_TRGM` | the DigiCert and Microsoft root CAs Azure documents; `verify-full` |
| Crunchy, Aiven, Neon and others | usually available; check the provider's extension list | the provider's CA |

`config check --connect` reports each extension as `installed`, `available` or `missing`, the server version and
whether the connection is encrypted. Connection poolers (PgBouncer, RDS Proxy) work in session pooling mode; the
job queue uses `LISTEN/NOTIFY`, which transaction pooling breaks.

## Redis-compatible caches

The cache holds sessions, caches, rate limits and realtime events. Agnostic uses strings with expiry, hashes, sets,
sorted sets, streams (`XADD … MAXLEN`, `XRANGE`), `PUBLISH` and `EVAL` (Lua). It needs neither `CONFIG`, `CLIENT`,
`KEYS` nor `FLUSHALL`, which managed services often disable.

| Service | Notes |
|---|---|
| AWS ElastiCache / MemoryDB | enable in-transit encryption and use `rediss://`; AUTH token or an ACL user in the URL (`rediss://user:password@…`); cluster mode is not supported, use a replication group's primary endpoint |
| Google Memorystore for Redis / Valkey | in-transit encryption with the instance's CA (`AGNOSTIC_REDIS__TLS__CA_FILE`); AUTH string in the URL |
| Azure Cache for Redis | TLS port 6380 (`rediss://:<access key>@<name>.redis.cache.windows.net:6380/0`); Entra ID auth isn't supported, use an access key |
| Valkey 8+, DragonflyDB 1.x | supported and tested in CI |
| Sentinel | `AGNOSTIC_REDIS__SENTINELS=host1:26379,host2:26379` and `AGNOSTIC_REDIS__SENTINEL_MASTER` |

`config check --connect` runs each command family against throwaway keys and fails with the refused commands and the
server's message (`unsupported: EVAL (NOSCRIPT …)`), so an ACL that is too strict shows up before people sign in.
Losing the cache degrades caches and realtime and signs people out; it loses no data.

## S3-compatible object storage

The audit archive speaks S3 with path-style URLs (`https://<endpoint>/<bucket>/<key>`) and AWS Signature Version 4,
so it works with AWS S3, MinIO, Ceph, SeaweedFS, Cloudflare R2, Wasabi and others.

- **Object Lock** (governance or compliance mode) must be enabled when the bucket is created. Agnostic sets the
  retain-until date on every archived object.
- **Credentials** need `PutObject`, `GetObject`, `HeadObject` and, for *Test write*, `DeleteObject` on the prefix.
- **Endpoints** with a private CA are trusted through `AGNOSTIC_TLS__CA_FILE`.
- `config check --connect` checks the bucket answers and accepts the credentials without writing anything.
