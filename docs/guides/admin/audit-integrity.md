# Audit integrity

The audit log can prove it wasn't changed: a hash chain links every event to the one before it, and each archived
month comes with a manifest that pins its content. This guide verifies both and restores archived months.

## The hash chain

With *Hash chain* on (*Organization › Audit retention*), every new event stores the hash of the previous one and its
own hash, `sha256(previous hash + the event's canonical JSON)`. Changing, inserting or removing an event breaks the
link at that point.

```bash
agnostic audit verify                                   # the whole chain
agnostic audit verify --since 2026-10-01 --until 2026-11-01
```

It prints how many chained events it checked, or the first event where the chain breaks, and exits with 1 when it
is broken. Run it on a schedule and after restores.

## Archived months

With the archive on, months leaving the hot window are written to your bucket as zstd-compressed JSONL with a
manifest (`audit-events-YYYY-MM.manifest.json`: event count, size, SHA-256, chain head, creation time), read back and
checked, and only then dropped from the database. See the SIEM and archive settings in *Organization › Audit
retention*.

```bash
agnostic audit archives list
agnostic audit archives verify 2025-08
agnostic audit archives verify --all
```

`verify` downloads the archive and checks, without restoring anything:

- the object's SHA-256 against the manifest **and** against the one recorded in the database when it was archived;
- its size against the store's and the manifest's;
- that it decompresses and every line is an event;
- the event count against the manifest;
- that every event belongs to the month;
- the hash chain inside the file, and that its last link is the manifest's chain head.

Damaged months are listed with what failed, and the command exits with 1. Each verification is audited
(`audit.archive_verify`, intact or damaged).

## Restoring a month

```bash
agnostic audit restore 2025-08
```

or *Restore for search* on the page. The archive is verified as above, loaded into the database, and searchable for
7 days; then maintenance drops it again (it is never re-archived). A damaged archive is refused.

## WORM storage

Create the bucket with Object Lock and choose **compliance** mode with an archive retention period: then nobody,
including the account's administrators, can delete or overwrite an archived month before the date. **Governance**
mode can be bypassed by users with the right permission.

## Drills

The [restore drill](../runbooks/restore-drill.md) restores a database backup and runs `audit verify` and
`audit archives verify --all` on the copy. It is part of every release.
