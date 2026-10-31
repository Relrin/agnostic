"""Adapters from the application ports to kernel job services."""

from __future__ import annotations

from agnostic_kernel.jobs import JobProgressReporter, JobQueue

COMPOSE_REPLY_TASK = "hello.compose_reply"
HEARTBEAT_TASK = "hello.heartbeat"


class QueuedReplyScheduler:
    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    async def schedule_reply(self, greeting_id: str) -> int:
        return await self._queue.defer(COMPOSE_REPLY_TASK, greeting_id=greeting_id)


class KernelProgressReporter:
    def __init__(self, reporter: JobProgressReporter) -> None:
        self._reporter = reporter

    async def report(self, job_id: int, progress: float, message: str) -> None:
        await self._reporter.report(job_id, COMPOSE_REPLY_TASK, progress, message=message)
