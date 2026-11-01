# Background jobs

Durable jobs run on PostgreSQL with [Procrastinate](https://procrastinate.readthedocs.io/). Redis is only 
used for live progress events.

## Declare a job

```python
# agnostic_instances/jobs.py
async def check_health(context: procrastinate.JobContext, timestamp: int) -> None:  # periodic jobs get `timestamp`
    async with job_container(context) as container:      # request-scoped DI, like an HTTP request
        results = await (await container.get(CheckHealth))()
    log.debug("instances.health", results=results)
```

```python
# agnostic_instances/module.py
def jobs(self) -> Iterable[JobSpec]:
    settings = InstancesSettings()
    return (
        JobSpec(name="instances.check_health", func=jobs.check_health, queue="instances", periodic=settings.health_cron),
        JobSpec(name="instances.refresh_snapshots", func=jobs.refresh_snapshots, queue="instances",
                periodic=settings.snapshot_cron),
    )
```

- Name jobs `<module>.<verb_noun>`; the name is the contract, so don't rename a job that may be queued.
- Arguments must be JSON values. Pass ids, not objects.
- Periodic schedules are de-duplicated across workers.
- `queue=` puts a job on its own queue (`instances`, `audit`, `git`, …); `agnostic worker -q instances` runs only
  that queue.

## Defer a job

From a use case, through a port, using the kernel's `JobQueue`:

```python
job_id = await job_queue.defer("notes.reindex", note_id=note.id)
```

Commit your data before deferring: the job runs in another transaction and may start at once. A transactional
outbox arrives in a later phase.

## Report progress

```python
await reporter.report(job_id, "notes.reindex", 0.5, message="Half way")
```

This upserts a row in `kernel_job_progress` and publishes it on `evt:job:{job_id}`. If Redis is down the row is
still written and a warning is logged.

## Run workers

```bash
uv run agnostic worker                   # all queues
uv run agnostic worker -q instances -q audit --concurrency 4
```

With SQLite, or with `AGNOSTIC_JOBS__MODE=embedded`, jobs run inside the API process instead and `agnostic worker`
exits with an explanation. On SQLite the queue is in memory: queued jobs are lost when the API stops.
