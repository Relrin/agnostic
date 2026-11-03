"""Background jobs on Postgres with Procrastinate.

Modules declare :class:`~agnostic_kernel.modules.JobSpec`s; the kernel registers them on one Procrastinate ``App``.
Inside a job, :func:`job_container` gives a request-scoped dishka container, so jobs use the same services as the
API. Long-running jobs report progress through :class:`JobProgressReporter`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from typing import Any, cast

import orjson
import procrastinate
from dishka import AsyncContainer
from procrastinate.app import WorkerOptions
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.testing import InMemoryConnector
from procrastinate.types import JSONValue
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import Insert, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agnostic_kernel.db import JOBS_SCHEMA, psycopg_conninfo
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import JobSpec
from agnostic_kernel.settings import DatabaseSettings
from agnostic_kernel.tables import JobProgressRow

CONTAINER_KEY = "agnostic.container"

log = get_logger(__name__)


def create_jobs_app(settings: DatabaseSettings) -> procrastinate.App:
    """Procrastinate on PostgreSQL; on SQLite an in-memory queue that only an embedded worker can drain."""
    if settings.backend == "sqlite":
        return procrastinate.App(connector=InMemoryConnector())
    connector = procrastinate.PsycopgConnector(
        conninfo=psycopg_conninfo(settings, search_path=JOBS_SCHEMA),
        min_size=1,
        max_size=4,
    )
    return procrastinate.App(connector=connector)


def register_jobs(app: procrastinate.App, specs: Iterable[JobSpec]) -> list[str]:
    """Register job specs as tasks (and periodic schedules). Returns the registered task names."""
    names: list[str] = []
    for spec in specs:
        task = app.task(name=spec.name, queue=spec.queue, retry=spec.retry, pass_context=True)(spec.func)
        if spec.periodic:
            app.periodic(cron=spec.periodic, periodic_id=spec.name)(task)  # pyright: ignore[reportUnknownArgumentType]
        names.append(spec.name)
    return names


def worker_options(
    container: AsyncContainer,
    *,
    queues: Iterable[str] | None,
    concurrency: int,
    install_signal_handlers: bool = True,
) -> WorkerOptions:
    """Options for ``App.run_worker_async``; ``additional_context`` carries the container to the jobs."""
    options = WorkerOptions(
        concurrency=concurrency,
        install_signal_handlers=install_signal_handlers,
        additional_context={CONTAINER_KEY: container},
    )
    if queues:
        options["queues"] = list(queues)
    return options


@asynccontextmanager
async def job_container(context: procrastinate.JobContext) -> AsyncGenerator[AsyncContainer]:
    """Request-scoped container for the duration of one job."""
    values = cast("dict[str, object]", context.additional_context)
    app_container = values.get(CONTAINER_KEY)
    if not isinstance(app_container, AsyncContainer):
        msg = "the worker was started without a dishka container (use agnostic worker)"
        raise TypeError(msg)
    async with app_container() as request_container:
        yield request_container


class JobQueue:
    """Deferring jobs by name, so callers don't import the task functions of other modules."""

    def __init__(self, app: procrastinate.App) -> None:
        self._app = app

    async def defer(self, task_name: str, /, *, lock: str | None = None, **kwargs: JSONValue) -> int:
        """Queue ``task_name``. Jobs that share a ``lock`` run one after another, never at the same time."""
        return await self._app.configure_task(task_name, lock=lock).defer_async(**kwargs)

    async def defer_once(
        self, task_name: str, /, *, queueing_lock: str, lock: str | None = None, **kwargs: JSONValue
    ) -> int | None:
        """Queue ``task_name`` unless a job with the same ``queueing_lock`` is already waiting (then ``None``).

        For bursts of the same trigger (webhook redeliveries, repeated pushes): one waiting job covers them all.
        """
        deferrer = self._app.configure_task(task_name, lock=lock, queueing_lock=queueing_lock)
        try:
            return await deferrer.defer_async(**kwargs)
        except AlreadyEnqueued:
            return None


class JobProgressReporter:
    """Writes job progress to ``kernel_job_progress`` and announces it on ``evt:job:{id}``."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        self._sessionmaker = sessionmaker
        self._redis = redis

    async def report(
        self,
        job_id: int,
        kind: str,
        progress: float,
        *,
        message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        progress = min(max(progress, 0.0), 1.0)
        values = {"job_id": job_id, "kind": kind, "progress": progress, "message": message, "result": result}
        changes = {"progress": progress, "message": message, "result": result, "updated_at": func.now()}
        async with self._sessionmaker.begin() as session:
            _ = await session.execute(_upsert(session.get_bind().dialect.name, values, changes))
        try:
            _ = await self._redis.publish(f"evt:job:{job_id}", orjson.dumps(values))  # pyright: ignore[reportUnknownMemberType]
        except (RedisError, OSError) as exc:
            # Redis is ephemeral: losing it costs the live update, never the job.
            log.warning("jobs.progress_publish_failed", job_id=job_id, error=str(exc))


def _upsert(dialect: str, values: dict[str, Any], changes: dict[str, Any]) -> Insert:
    if dialect == "postgresql":
        pg = postgresql.insert(JobProgressRow).values(**values)
        return pg.on_conflict_do_update(index_elements=[JobProgressRow.job_id], set_=changes)
    lite = sqlite.insert(JobProgressRow).values(**values)
    return lite.on_conflict_do_update(index_elements=[JobProgressRow.job_id], set_=changes)
