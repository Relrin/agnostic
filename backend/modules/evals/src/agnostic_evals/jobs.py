"""Background jobs of the evals module."""

from __future__ import annotations

from typing import Any, cast

import procrastinate
from dishka import AsyncContainer

from agnostic_evals.application.batches import RUN_TASK
from agnostic_evals.application.run_batch import RunBatch
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.jobs import CONTAINER_KEY, job_container

__all__ = ["RUN_TASK", "run_batch"]


class ScopedCaller:
    """One request scope per eval call, so concurrent cases never share a database session."""

    def __init__(self, app: AsyncContainer) -> None:
        self._app = app

    async def __call__(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        body: Any,  # noqa: ANN401
    ) -> GatewayResponse:
        async with self._app() as container:
            gateway = await container.get(GatewayFacade)
            return await gateway.call(principal, instance, method, path, json=body)


async def run_batch(context: procrastinate.JobContext, batch_id: str) -> None:
    app = cast("dict[str, object]", context.additional_context).get(CONTAINER_KEY)
    async with job_container(context) as container:
        runner = await container.get(RunBatch)
        caller = ScopedCaller(app) if isinstance(app, AsyncContainer) else None
        _ = await runner(batch_id, caller)
