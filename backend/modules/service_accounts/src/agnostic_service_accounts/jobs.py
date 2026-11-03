"""Background jobs of the service_accounts module."""

from __future__ import annotations

import procrastinate

from agnostic_kernel.jobs import job_container
from agnostic_service_accounts.application.accounts import ServiceAccounts

POLL_TASK = "service_accounts.poll_last_used"


async def poll_last_used(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(ServiceAccounts)).poll()
