"""Background jobs of the tool catalog module (queue ``instances``)."""

from __future__ import annotations

import procrastinate

from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.jobs import job_container
from agnostic_tool_catalog.application.ports import RuntimeBridge


async def notify(context: procrastinate.JobContext, instance_ids: list[str]) -> None:
    """Ask the bridges of the affected instances to pull the catalog now (each pulls on its own interval anyway)."""
    async with job_container(context) as container:
        instances = await container.get(InstancesFacade)
        bridge = await container.get(RuntimeBridge)
        for instance in await instances.list():
            if not instance_ids or instance.id in instance_ids:
                _ = await bridge.nudge(instance)
