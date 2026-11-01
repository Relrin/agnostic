"""Background jobs of the search module."""

from __future__ import annotations

import procrastinate

from agnostic_kernel.jobs import job_container
from agnostic_search.application.use_cases import reindex

REINDEX_TASK = "search.reindex"


async def reindex_all(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await reindex(container)
