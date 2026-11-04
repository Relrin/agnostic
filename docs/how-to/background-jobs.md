# Background jobs

Durable jobs run on PostgreSQL with [Procrastinate](https://procrastinate.readthedocs.io/); Redis only carries live
progress events. Kernel pieces: `agnostic_kernel.jobs` (`JobQueue`, `JobProgressReporter`, `job_container`) and
`JobSpec` in `agnostic_kernel.modules`.

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

- Name jobs `<module>.<verb_noun>`. The name is the contract: don't rename a job that may be queued.
- Arguments are JSON values. Pass ids, not objects.
- Periodic schedules are de-duplicated across workers.
- `queue=` puts a job on its own queue (`instances`, `audit`, `git`, …); `agnostic worker -q instances` runs only
  that queue.

## Defer a job

From a use case, through a port backed by the kernel's `JobQueue`:

```python
job_id = await job_queue.defer("notes.reindex", note_id=note.id)
```

Commit your data first: the job runs in its own transaction and may start at once.

For triggers that come in bursts (webhook redeliveries, repeated pushes), `defer_once` queues the job unless one with
the same `queueing_lock` is already waiting, and then returns `None`:

```python
await job_queue.defer_once("sources.fetch", queueing_lock=f"fetch:{source.id}", lock=f"sources:{source.id}",
                           source_id=source.id, reason="push")
```

`lock` makes jobs that share it run one after another; `queueing_lock` keeps more than one from waiting.

## Report progress

```python
await reporter.report(job_id, "notes.reindex", 0.5, message="Half way")
```

Upserts a row in `kernel_job_progress` and publishes it on `evt:job:{job_id}`. With Redis down the row is still
written and a warning is logged.

## Run workers

```bash
uv run agnostic worker                   # all queues
uv run agnostic worker -q instances -q audit --concurrency 4
uv run agnostic worker -q git            # code sources: needs git and the mirrors volume
```

With `AGNOSTIC_JOBS__MODE=embedded` (the default on SQLite) jobs run inside the API process. On SQLite
`agnostic worker` exits with code 2 and an explanation, and the queue is in memory: queued jobs are lost when the
API stops.
