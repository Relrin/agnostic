"""Background jobs of the scheduler module."""

from __future__ import annotations

import procrastinate

from agnostic_kernel.jobs import job_container
from agnostic_scheduler.application.watch import WatchScheduleFailures

WATCH_TASK = "scheduler.watch_failures"


async def watch_failures(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(WatchScheduleFailures))()
