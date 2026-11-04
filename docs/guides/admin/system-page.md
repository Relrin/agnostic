# The System page

*System* (in the sidebar footer) shows what the control plane itself is doing. It refreshes every 15 seconds.

| Who | Scope | Can |
|---|---|---|
| Owners | `org:system:read`, `org:system:manage` | see everything, retry and discard failed jobs |
| Administrators | `org:system:read` | see everything |

## Sections

| Section | Shows |
|---|---|
| Versions | Agnostic, Python, the database server, the cache server, every enabled module |
| Background work | one line per module with work in flight: notification deliveries (failed in 24 h, waiting over 15 min), SIEM destinations (state, failures, last error), the audit archive (last run or its error), AgentOS trail ingestion (how far behind), code-source webhooks |
| Job queues | per queue: waiting, running, failed, the age of the oldest due job; the cache hit ratio since the API process started |
| Failed jobs | jobs that ran out of retries, newest first, with their task, queue, attempts and when they failed |
| Instance polling | each runtime's status, last seen, latency and network mode |
| Endpoints | *Check endpoints* probes the database, migrations, cache, master key, SMTP, sign-in providers, the audit archive and every runtime, like `agnostic config check --connect` |

## Failed jobs

A job fails after its retries; it is kept so you can see what failed. Only argument names are shown, not values.

- **Retry** queues it again, to run as soon as a worker is free.
- **Discard** deletes it.

Both need `org:system:manage` and are audited (`system.job.retry`, `system.job.discard`). Retry after fixing the
cause; the [failed jobs runbook](../runbooks/job-dead-letters.md) lists common ones.

## API

| Route | Does |
|---|---|
| `GET /api/v1/system/status` | the overview above |
| `POST /api/v1/system/checks` | runs the endpoint checks |
| `GET /api/v1/system/jobs/failed?limit=&before=` | failed jobs, paged by id |
| `POST /api/v1/system/jobs/{id}/retry` | retry |
| `DELETE /api/v1/system/jobs/{id}` | discard |
