"""Background jobs of the audit module."""

from __future__ import annotations

import procrastinate

from agnostic_audit.application.use_cases import MaintainPartitions
from agnostic_kernel.jobs import job_container

MAINTENANCE_TASK = "audit.maintain_partitions"


async def maintain_partitions(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    """Create next months' partitions and drop the ones past retention."""
    async with job_container(context) as container:
        await (await container.get(MaintainPartitions))()
