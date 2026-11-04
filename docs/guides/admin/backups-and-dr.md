# Backups and disaster recovery

## What to back up

| What | Why | How |
|---|---|---|
| The control-plane PostgreSQL database | everything Agnostic knows: people, roles, instances, keys (sealed), Studio metadata, audit log, settings | your database tooling: PITR with WAL archiving, managed snapshots, `pg_dump` |
| The master key | opens every stored secret; it is not in the database | your secret store, plus an offline copy |
| The audit archive bucket | archived audit months (when the archive is on) | your object storage's own replication or versioning; Object Lock for WORM |
| The values or `.env` you deploy with | settings | your configuration repository |

Not Agnostic's to back up: the AgentOS runtimes' own databases (sessions, memories, knowledge, component configs).
Back those up the way you run AgentOS. The cache holds nothing that can't be rebuilt; losing it signs people out and
empties caches.

## Recovery objectives

With continuous WAL archiving (PITR), plan for:

| | Target |
|---|---|
| RPO | ≤ 5 minutes (the WAL archive interval) |
| RTO | ≤ 1 hour: restore the database, deploy the image, run the checks |

Nightly logical dumps alone give an RPO of 24 hours. Test restores, not just backups: see the drill below.

## Restore drill

`scripts/restore_drill.sh` does what a restore does, against a copy, and proves the copy is complete:

1. `pg_dump --format=custom` of the database.
2. `pg_restore` into a fresh database `agnostic_restore_drill`.
3. The same number of audit events before and after; migrations current; `agnostic audit verify` (the hash chain);
   `agnostic secrets status` (every secret opens with the configured key); `agnostic audit archives verify --all`;
   `agnostic config check --connect`.

```bash
AGNOSTIC_DATABASE__URL=postgresql://… AGNOSTIC_REDIS__URL=redis://… AGNOSTIC_SECRETS__MASTER_KEY=… \
  bash scripts/restore_drill.sh
```

It runs nightly in CI and is part of every release. See the [restore drill runbook](../runbooks/restore-drill.md).

## Disaster recovery runbook

1. **Restore the database** to a new PostgreSQL server (PITR to just before the incident, or the latest snapshot).
   Check `citext` and `pg_trgm` are available.
2. **Use the same master key.** Configure `AGNOSTIC_SECRETS__MASTER_KEY` (and any previous keys) exactly as before;
   with a KMS provider, the restored processes need access to the same KMS key.
3. **Point the deployment at the restored database** (`AGNOSTIC_DATABASE__URL`) and a cache (a new empty one is fine).
4. **Deploy** the same Agnostic version that wrote the backup. Upgrade afterwards, not during the recovery.
5. **Verify**:

   ```bash
   agnostic db current            # up to date
   agnostic config check --connect
   agnostic audit verify
   agnostic secrets status
   ```

6. **Reconnect** what the outage may have changed: *Test connection* on every instance (System page › Endpoints
   checks all of them). People sign in again; their sessions were in the cache.

If the master key is lost, the database still restores but sealed secrets don't open. Reconnect each instance (new
key pairs), re-enter IdP client secrets, SIEM and notification credentials and the archive secret, and recreate
service-account tokens.
