# Runbook: failed jobs

Background jobs (notification deliveries, SIEM streaming, audit maintenance, evaluation batches, code-source syncs,
instance health checks, the assistant's answers) run on workers. A job that ran out of retries stays in the queue as
**failed** so you can see it and decide.

## Symptoms

- *System › Job queues* shows failed jobs; `agnostic_jobs_failed` is above 0.
- Something didn't happen: an email wasn't sent, a sync didn't run, an evaluation stopped.
- `agnostic_jobs_oldest_wait_seconds` grows: jobs wait and no worker picks them up (a different problem, below).

## Confirm

*System › Failed jobs* lists each with its task, queue, attempts and when it failed. Find the cause in the worker's
logs around that time (search for the task name; every line has the job and request ids).

## Fix

| Task | Usual cause | Fix |
|---|---|---|
| `notifications.deliver` | SMTP, Slack or webhook unreachable or credentials changed | fix the channel in *Settings › Notifications*, *Test*, then retry |
| `audit.*` (sinks, maintenance, restore) | the SIEM or the archive bucket fails | [SIEM backlog](siem-backlog.md), the archive settings' *Test write* |
| `sources.*` | the git host is unreachable or the credentials expired | reconnect in *Studio › Code sources* |
| `evals.run_batch` | the runtime failed during the batch | check the instance, start the evaluation again |
| `kernel.domain_event` | a module's event handler failed | read the error; retry once the cause is fixed |

Then on *System › Failed jobs*: **Retry** queues the job again, **Discard** deletes it (a job that no longer makes
sense, such as a notification about something long resolved). Both need `org:system:manage` and are audited.

### Jobs wait but nothing runs

- Are workers running? `docker compose ps worker`.
- Do they listen to the queue? `AGNOSTIC_JOBS__QUEUES` (empty means all).
- Are they busy? Run more workers (`docker compose up -d --scale worker=3`) or raise `AGNOSTIC_JOBS__CONCURRENCY`.
- Can they reach PostgreSQL? Workers log connection errors at start.

## Verify

The retried job leaves the failed list, its effect happened (the email arrived, the sync ran), and
`agnostic_jobs_failed` and `agnostic_jobs_oldest_wait_seconds` are back to normal.
