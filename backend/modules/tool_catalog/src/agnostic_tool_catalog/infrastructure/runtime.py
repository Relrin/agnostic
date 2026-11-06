"""Calls to a runtime's bridge, made as the control plane (catalog upkeep, never on someone's behalf)."""

from __future__ import annotations

from typing import Any, cast

import orjson
from procrastinate.types import JSONValue

from agnostic_agentos_client import AgentOSError
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.jobs import JobQueue
from agnostic_kernel.logging import get_logger
from agnostic_tool_catalog.application.ports import (
    BRIDGE_PROBE,
    BRIDGE_STATUS,
    BRIDGE_SYNC,
    BRIDGE_TOOLKITS,
    NOTIFY_TASK,
)

log = get_logger(__name__)

STATUS_TTL = 15.0
"""Studio asks on every registry load; the bridge's report changes at most once per pull."""
UNAVAILABLE = b"null"


class BridgeClient:
    def __init__(self, instances: InstancesFacade, store: EphemeralStore) -> None:
        self._instances = instances
        self._store = store

    async def status(self, instance: Instance) -> dict[str, Any] | None:
        key = f"tool_catalog:status:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            value = orjson.loads(cached)
            return cast("dict[str, Any]", value) if isinstance(value, dict) else None
        try:
            body = await self._instances.system_call(instance, "GET", BRIDGE_STATUS)
        except AgentOSError:
            body = None
        report = cast("dict[str, Any]", body) if isinstance(body, dict) else None
        await self._store.set(key, orjson.dumps(report) if report is not None else UNAVAILABLE, ttl=STATUS_TTL)
        return report

    async def nudge(self, instance: Instance) -> bool:
        await self._store.delete(f"tool_catalog:status:{instance.id}")
        try:
            _ = await self._instances.system_call(instance, "POST", BRIDGE_SYNC)
        except AgentOSError as exc:
            log.info("tool_catalog.nudge_failed", instance=instance.id, detail=str(exc))
            return False
        return True

    async def probe(self, instance: Instance, item: dict[str, Any]) -> dict[str, Any]:
        body = await self._instances.system_call(instance, "POST", BRIDGE_PROBE, json=item)
        return cast("dict[str, Any]", body) if isinstance(body, dict) else {}

    async def toolkits(self, instance: Instance) -> dict[str, Any] | None:
        try:
            body = await self._instances.system_call(instance, "GET", BRIDGE_TOOLKITS)
        except AgentOSError:
            return None
        if not isinstance(body, dict):
            return None
        report = cast("dict[str, Any]", body)
        return report if report.get("toolkits") else None


class JobNotifyQueue:
    """Nudges run as a job: an unreachable runtime must not hold up the person who saved the entry."""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    async def notify(self, instance_ids: list[str]) -> None:
        try:
            _ = await self._queue.defer_once(
                NOTIFY_TASK,
                queueing_lock=f"tool_catalog:notify:{','.join(instance_ids) or '*'}",
                instance_ids=list[JSONValue](instance_ids),
            )
        except Exception as exc:  # noqa: BLE001  (best effort: every bridge pulls on its own interval anyway)
            log.info("tool_catalog.notify_not_queued", detail=str(exc))
