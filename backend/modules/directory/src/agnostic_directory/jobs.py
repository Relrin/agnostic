"""Background jobs of the directory module."""

from __future__ import annotations

import procrastinate

from agnostic_directory.application.google import GoogleSyncRunner
from agnostic_directory.application.reconcile import Reconcile
from agnostic_kernel.jobs import job_container

GOOGLE_SYNC_TASK = "directory.google_sync"
RECONCILE_TASK = "directory.reconcile"


async def google_sync(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(GoogleSyncRunner)).run(scheduled=True)


async def reconcile(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(Reconcile))()
