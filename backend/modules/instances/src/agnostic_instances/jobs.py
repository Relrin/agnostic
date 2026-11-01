"""Background jobs of the instances module (queue ``instances``)."""

from __future__ import annotations

import procrastinate

from agnostic_instances.application.use_cases import CheckHealth, RefreshAllSnapshots
from agnostic_kernel.jobs import job_container
from agnostic_kernel.logging import get_logger

HEALTH_TASK = "instances.check_health"
SNAPSHOT_TASK = "instances.refresh_snapshots"

log = get_logger(__name__)


async def check_health(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        results = await (await container.get(CheckHealth))()
    log.debug("instances.health", results=results)


async def refresh_snapshots(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        count = await (await container.get(RefreshAllSnapshots))()
    log.debug("instances.snapshots", refreshed=count)
