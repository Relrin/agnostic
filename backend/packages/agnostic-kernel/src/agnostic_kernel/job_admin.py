"""What the job queues are doing: depth and lag per queue, failed jobs (dead letters), retry and discard.

Read by the System page and the ``agnostic_jobs_*`` metrics. On PostgreSQL the lag comes from Procrastinate's
event table; the in-memory queue used with SQLite reports counts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import orjson
import procrastinate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel import metrics
from agnostic_kernel.db import JOBS_SCHEMA


@dataclass(frozen=True, slots=True)
class QueueStats:
    queue: str
    waiting: int
    running: int
    failed: int
    oldest_wait_seconds: float | None = None
    """Age of the oldest job that is due and not picked up yet."""


@dataclass(frozen=True, slots=True)
class FailedJob:
    id: int
    queue: str
    task: str
    attempts: int
    failed_at: datetime | None
    argument_names: tuple[str, ...]
    """Only the names: arguments can carry ids and text that don't belong on an admin screen."""


_LAG = f"""
SELECT j.queue_name, EXTRACT(EPOCH FROM now() - min(COALESCE(j.scheduled_at, e.at)))
FROM {JOBS_SCHEMA}.procrastinate_jobs j
JOIN {JOBS_SCHEMA}.procrastinate_events e ON e.job_id = j.id AND e.type = 'deferred'
WHERE j.status = 'todo' AND (j.scheduled_at IS NULL OR j.scheduled_at <= now())
GROUP BY j.queue_name
"""  # noqa: S608  (the schema name is a constant)

_FAILED = f"""
SELECT j.id, j.queue_name, j.task_name, j.attempts, j.args,
       (SELECT max(e.at) FROM {JOBS_SCHEMA}.procrastinate_events e WHERE e.job_id = j.id AND e.type = 'failed')
FROM {JOBS_SCHEMA}.procrastinate_jobs j
WHERE j.status = 'failed' AND (CAST(:before AS bigint) IS NULL OR j.id < :before)
ORDER BY j.id DESC
LIMIT :limit
"""  # noqa: S608


class JobAdmin:
    def __init__(self, app: procrastinate.App, engine: AsyncEngine) -> None:
        self._app = app
        self._engine = engine

    @property
    def _postgres(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    async def queues(self) -> list[QueueStats]:
        rows = await self._app.job_manager.list_queues_async()
        lag: dict[str, float] = {}
        if self._postgres:
            async with self._engine.connect() as connection:
                lag = {str(name): float(age) for name, age in await connection.execute(text(_LAG)) if age is not None}
        return sorted(
            (
                QueueStats(
                    queue=str(row["name"]),
                    waiting=int(row["todo"]),
                    running=int(row["doing"]),
                    failed=int(row["failed"]),
                    oldest_wait_seconds=lag.get(str(row["name"])),
                )
                for row in rows
            ),
            key=lambda stats: stats.queue,
        )

    async def failed(self, *, limit: int = 50, before: int | None = None) -> list[FailedJob]:
        if self._postgres:
            async with self._engine.connect() as connection:
                rows = await connection.execute(text(_FAILED), {"limit": limit, "before": before})
                return [
                    FailedJob(
                        id=int(job_id),
                        queue=str(queue),
                        task=str(task),
                        attempts=int(attempts),
                        failed_at=failed_at,
                        argument_names=tuple(sorted(_args(args))),
                    )
                    for job_id, queue, task, attempts, args, failed_at in rows
                ]
        jobs = sorted(
            (job for job in await self._app.job_manager.list_jobs_async(status="failed") if job.id is not None),
            key=lambda job: job.id or 0,
            reverse=True,
        )
        return [
            FailedJob(
                id=job.id or 0,
                queue=job.queue,
                task=job.task_name,
                attempts=job.attempts,
                failed_at=None,
                argument_names=tuple(sorted(job.task_kwargs)),
            )
            for job in jobs
            if before is None or (job.id or 0) < before
        ][:limit]

    async def retry(self, job_id: int) -> None:
        """Queue a failed job again, to run as soon as a worker is free."""
        await self._app.job_manager.retry_job_by_id_async(job_id, retry_at=datetime.now(UTC))

    async def discard(self, job_id: int) -> bool:
        """Delete a failed job; ``False`` when there is no failed job with that id."""
        if not self._postgres:
            return False
        async with self._engine.begin() as connection:
            # Procrastinate's triggers name their types unqualified.
            _ = await connection.execute(text(f"SET LOCAL search_path TO {JOBS_SCHEMA}, public"))
            result = await connection.execute(
                text(f"DELETE FROM {JOBS_SCHEMA}.procrastinate_jobs WHERE id = :id AND status = 'failed'"),  # noqa: S608
                {"id": job_id},
            )
            return bool(result.rowcount)


def _args(raw: object) -> list[str]:
    loaded: object = orjson.loads(raw) if isinstance(raw, str | bytes) else raw
    return [str(key) for key in cast("dict[str, Any]", loaded)] if isinstance(loaded, dict) else []


async def refresh_job_metrics(admin: JobAdmin) -> None:
    for stats in await admin.queues():
        metrics.job_queue_depth.labels(stats.queue).set(stats.waiting)
        metrics.job_queue_running.labels(stats.queue).set(stats.running)
        metrics.job_queue_failed.labels(stats.queue).set(stats.failed)
        metrics.job_queue_lag.labels(stats.queue).set(stats.oldest_wait_seconds or 0.0)
