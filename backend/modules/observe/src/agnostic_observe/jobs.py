"""Background jobs of the observe module."""

from __future__ import annotations

import procrastinate

from agnostic_kernel.jobs import job_container
from agnostic_observe.application.overview import WarmOverviews

WARM_TASK = "observe.warm_overviews"


async def warm_overviews(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(WarmOverviews))()
