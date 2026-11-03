# SIEM streaming and the audit archive

The audit log keeps every control-plane change, every denial and a sample of gateway reads (all reads with the org
setting `audit_log_all_reads`). This guide sends it to a SIEM and archives old months to S3-compatible storage. Both
are configured by Owners and Administrators in *Organization › SIEM streaming* and *Organization › Audit retention*.

## Streaming to a SIEM

Add a destination, pick a format (JSON, OCSF or CEF) and *Test delivery*. Events are delivered within seconds and at
least once: each destination has a cursor that advances only after it accepted a batch, so a restart or an outage
re-sends instead of losing events. Deduplicate on the event `id`. A destination that keeps failing turns *Failing*
and Owners and Administrators are notified; *Pause* stops delivery without losing the position.

| Destination | Settings | Notes |
|---|---|---|
| HTTPS webhook | URL, signing secret, extra headers | a JSON array per batch; `X-Agnostic-Signature: t=<unix>,v1=<hex>` where `v1 = HMAC-SHA256(secret, "<t>.<body>")`; `X-Agnostic-Event-Count` |
| Syslog | host, port, TLS (on by default), CA | RFC 5424 over TCP or TLS, one event per message (CEF or JSON body) |
| OTLP logs | endpoint, headers | OTLP/HTTP JSON to `<endpoint>/v1/logs`, for an OpenTelemetry collector |

Verifying a webhook signature (Python):

```python
import hashlib, hmac, time

def verify(secret: bytes, header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    if abs(time.time() - int(parts["t"])) > tolerance:
        return False
    expected = hmac.new(secret, parts["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

## Retention and the archive

Events stay searchable in PostgreSQL for the hot window (400 days by default). With the archive on, the daily
maintenance job handles each month that leaves the window:

1. writes the month's events as JSONL compressed with zstd, and a manifest (event count, SHA-256, chain head);
2. uploads both to `s3://<bucket>/<prefix>/audit-events-YYYY-MM.jsonl.zst` (and `….manifest.json`), reads them back
   and checks size and checksum;
3. records the month in *Archived months*, and only then drops the month's partition.

If any step fails the partition stays, the error is shown on the page and Owners and Administrators are notified.
Without the archive, months past the window are dropped.

Settings: endpoint (any S3-compatible service: AWS S3, MinIO, Ceph, SeaweedFS, Cloudflare R2…), bucket, prefix,
region, access key and secret (sealed, never shown again), Object Lock mode (governance or compliance, with the
archive retention as the retain-until date; the bucket must have Object Lock enabled), archive retention (none by
default: archives are kept until your bucket lifecycle rules remove them). *Test write* writes, reads back and
deletes a small object with the values in the form.

**Restore for search** brings an archived month back for 7 days: the archive is downloaded, checked against its
manifest and loaded into the database, where it is searchable like any other month, then dropped again. From a
shell: `agnostic audit restore 2025-08`.

## Integrity

With *Hash chain* on (*Audit retention*), each event's hash covers the previous event's hash, so a removed or
changed event breaks the chain from that point. `agnostic audit verify --since 2026-01-01` checks a range and exits
with 1 when the chain is broken; archive manifests record the chain head of their month.

Locally, `docker compose -f deploy/dev/compose.yml --profile archive up -d seaweedfs` starts an S3-compatible
store on http://localhost:8333 (access key `agnostic`, secret in `deploy/dev/seaweedfs/s3.json`; create the bucket
`agnostic-audit` first, e.g. with the AWS CLI and `--endpoint-url`).
