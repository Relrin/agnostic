# Runbook: restore drill

A backup is only as good as the last time it was restored. Run this drill before every release, after changing
backup tooling, and at least quarterly in production.

## What it proves

That a backup of the control-plane database restores into a working copy: the same audit events, migrations
current, the hash chain intact, every stored secret opening with the configured master key, archived audit months
verifying, every endpoint reachable.

## Run it

You need the PostgreSQL client tools of the server's major version (`pg_dump`, `pg_restore`, `psql`) and the same
settings as production (in particular the master key).

```bash
export AGNOSTIC_DATABASE__URL=postgresql://agnostic:…@db.example.com:5432/agnostic
export AGNOSTIC_REDIS__URL=rediss://…
export AGNOSTIC_SECRETS__MASTER_KEY=…
bash scripts/restore_drill.sh
```

It dumps the database, restores it into `agnostic_restore_drill` on the same server, checks the copy with
`agnostic db current`, `agnostic audit verify`, `agnostic secrets status`, `agnostic audit archives verify --all` and
`agnostic config check --connect`, compares the audit event counts, and drops the copy. Restoring onto another server
works the same way with that server's URL.

To drill your real backup (a PITR restore or a managed snapshot), restore it into a new database yourself, point
`AGNOSTIC_DATABASE__URL` at it and run the checks:

```bash
agnostic db current && agnostic audit verify && agnostic secrets status && agnostic audit archives verify --all
```

## When it fails

| Failure | Meaning |
|---|---|
| `secrets status` exits 1 | values need a master key that isn't configured: the drill's key differs from production, or a key was lost. Find the key before you need it |
| `audit verify` broken | the chain was broken in the backup: investigate the event it names (the audit log's own change history) |
| `archives verify` damaged | an archived object differs from its manifest: check the bucket's versioning and Object Lock |
| event counts differ | the dump or restore was incomplete; check `pg_restore`'s output |

Record the date, the backup used, the duration and the result in your release or operations log.
