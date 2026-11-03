"""Background jobs of the gateway module (queue ``gateway``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agnostic_gateway.application.ingest import IngestAuthz
from agnostic_kernel.jobs import job_container
from agnostic_kernel.logging import get_logger

if TYPE_CHECKING:
    import procrastinate

INGEST_TASK = "gateway.ingest_authz"

log = get_logger(__name__)


async def ingest_authz(context: procrastinate.JobContext, timestamp: int | None = None) -> None:  # noqa: ARG001
    """Copy every connected instance's AgentOS decision and change trails into the audit log."""
    async with job_container(context) as container:
        stored = await (await container.get(IngestAuthz))()
    if any(stored.values()):
        log.info("gateway.ingested_authz", stored=stored)
