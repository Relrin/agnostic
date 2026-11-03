"""Background jobs of the access module."""

from __future__ import annotations

import procrastinate

from agnostic_access.application.requests import TemporaryAccess
from agnostic_kernel.jobs import job_container

EXPIRE_TASK = "access.expire_bindings"


async def expire_bindings(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(TemporaryAccess)).expire()
