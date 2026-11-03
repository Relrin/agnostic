"""Background jobs of the audit module."""

from __future__ import annotations

import procrastinate

from agnostic_audit.application.archive import RESTORE_TASK, Archives, MaintainPartitions
from agnostic_audit.application.exports import EXPORT_TASK, Exports
from agnostic_audit.application.streaming import DELIVER_TASK, DeliverSinks
from agnostic_kernel.jobs import job_container
from agnostic_kernel.logging import get_logger

MAINTENANCE_TASK = "audit.maintain_partitions"
__all__ = ["DELIVER_TASK", "EXPORT_TASK", "MAINTENANCE_TASK", "RESTORE_TASK"]

log = get_logger(__name__)


async def maintain_partitions(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    """Create next months' partitions; archive (when on) and drop the ones past retention; clean up old exports."""
    async with job_container(context) as container:
        await (await container.get(MaintainPartitions))()
        removed = await (await container.get(Exports)).cleanup()
    if removed:
        log.info("audit.exports_expired", removed=removed)


async def deliver_sinks(context: procrastinate.JobContext, timestamp: int | None = None) -> None:  # noqa: ARG001
    """Stream new events to every enabled SIEM sink (periodic, and queued shortly after events are written)."""
    async with job_container(context) as container:
        delivered = await (await container.get(DeliverSinks))()
    if any(delivered.values()):
        log.debug("audit.delivered", delivered=delivered)


async def export_events(context: procrastinate.JobContext, export_id: str) -> None:
    async with job_container(context) as container:
        await (await container.get(Exports)).run(export_id)


async def restore_month(context: procrastinate.JobContext, month: str) -> None:
    async with job_container(context) as container:
        try:
            _ = await (await container.get(Archives)).restore(month)
        except Exception as exc:
            log.warning("audit.restore_failed", month=month, error=str(exc))
            raise
