# Background jobs

Durable jobs run on PostgreSQL with [Procrastinate](https://procrastinate.readthedocs.io/). Redis is only 
used for live progress events.

## Declare a job

```python
# jobs.py
async def compose_reply(context: procrastinate.JobContext, greeting_id: str) -> None:
    job_id = context.job.id
    async with job_container(context) as container:      # request-scoped DI, like an HTTP request
        use_case = await container.get(ComposeReply)
        await use_case(greeting_id, job_id)

async def heartbeat(context: procrastinate.JobContext, timestamp: int) -> None:   # periodic jobs get `timestamp`
    ...
```

```python
# module.py
def jobs(self) -> Iterable[JobSpec]:
    return (
        JobSpec(name="hello.compose_reply", func=jobs.compose_reply, retry=3),
        JobSpec(name="hello.heartbeat", func=jobs.heartbeat, periodic="*/5 * * * *"),
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
await job_queue.defer("hello.compose_reply", greeting_id=greeting.id)
```

Commit your data before deferring (see `CreateGreeting`): the job runs in another transaction and may start at
once. A transactional outbox arrives in P01.

## Report progress

```python
await reporter.report(job_id, "hello.compose_reply", 0.5, message="Half way")
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
