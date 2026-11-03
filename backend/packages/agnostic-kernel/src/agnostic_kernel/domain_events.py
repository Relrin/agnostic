"""Domain events between modules: one module announces something happened, others react in a background job.

A module publishes ``DomainEvents.publish("evals.regression", {...})`` after it committed its own change; every
module that declared an :class:`~agnostic_kernel.modules.EventHandlerSpec` for that name gets the payload in the
``kernel.domain_event`` job, with a request-scoped container. Publishers never import their subscribers, so modules
that can't depend on each other (notifications depends on access, access announces privileged grants) still talk.

Delivery is at-least-once per handler run: a failing handler is logged and doesn't stop the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import procrastinate
from procrastinate.types import JSONValue

from agnostic_kernel.jobs import JobQueue, job_container
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import JobSpec, LoadedModules

log = get_logger(__name__)

DISPATCH_TASK = "kernel.domain_event"


class DomainEvents:
    def __init__(self, queue: JobQueue, modules: LoadedModules) -> None:
        self._queue = queue
        self._subscribed = frozenset(spec.event for module in modules.enabled for spec in module.event_handlers())

    def subscribed(self, event: str) -> bool:
        return event in self._subscribed

    async def publish(self, event: str, payload: Mapping[str, Any]) -> None:
        """Queue ``event`` for its handlers; call it after committing. Never raises (the change already happened)."""
        if event not in self._subscribed:
            return
        try:
            _ = await self._queue.defer(DISPATCH_TASK, event=event, payload=cast("JSONValue", dict(payload)))
        except Exception as exc:  # noqa: BLE001  (a lost notification must not fail the request that caused it)
            log.warning("domain_events.defer_failed", domain_event=event, error=str(exc))


async def dispatch(context: procrastinate.JobContext, event: str, payload: dict[str, Any]) -> None:
    async with job_container(context) as container:
        modules = await container.get(LoadedModules)
        for module in modules.enabled:
            for spec in module.event_handlers():
                if spec.event != event:
                    continue
                try:
                    await spec.handler(container, payload)
                except Exception as exc:  # noqa: BLE001  (one subscriber's failure doesn't starve the others)
                    log.warning("domain_events.handler_failed", domain_event=event, module=module.name, error=str(exc))


def kernel_jobs() -> tuple[JobSpec, ...]:
    return (JobSpec(name=DISPATCH_TASK, func=dispatch, queue="default"),)
