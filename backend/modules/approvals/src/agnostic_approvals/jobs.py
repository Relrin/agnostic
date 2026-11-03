"""Background jobs of the approvals module."""

from __future__ import annotations

import procrastinate

from agnostic_approvals.application.watch import WatchApprovals
from agnostic_kernel.jobs import job_container

WATCH_TASK = "approvals.watch"


async def watch(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(WatchApprovals))()
