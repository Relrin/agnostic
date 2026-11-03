"""Deferring the audit module's jobs through Procrastinate."""

from __future__ import annotations

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued

from agnostic_kernel.jobs import JobQueue


class ProcrastinateJobs:
    def __init__(self, app: procrastinate.App, queue: JobQueue) -> None:
        self._app = app
        self._queue = queue

    async def defer(self, task_name: str, /, **kwargs: str) -> None:
        _ = await self._queue.defer(task_name, **kwargs)

    async def defer_once(self, task_name: str, *, delay_seconds: int) -> None:
        try:
            _ = await self._app.configure_task(
                task_name, queueing_lock=task_name, schedule_in={"seconds": delay_seconds}
            ).defer_async()
        except AlreadyEnqueued:
            return
