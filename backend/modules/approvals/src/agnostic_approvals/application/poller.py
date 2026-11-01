"""The pending-approvals count behind the nav badge: one replica asks each instance every few seconds.

AgentOS has no push channel for approvals yet, so the control plane polls ``GET /approvals/count`` as itself and
publishes ``approvals.count`` on the instance channel only when the number changes. A short lock in the ephemeral
store keeps several API replicas from polling the same instance in the same interval.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, cast

from dishka import AsyncContainer

from agnostic_agentos_client import AgentOSError, CapabilityDisabledError, InstanceUnreachableError
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

DISABLED_BACKOFF = 300.0
COUNT_KEY = "apr:count:{instance}"


class ApprovalsCountPoller:
    def __init__(self, instances: InstancesFacade, store: EphemeralStore, bus: EventBus, interval: float) -> None:
        self._instances = instances
        self._store = store
        self._bus = bus
        self._interval = interval

    async def poll_all(self) -> None:
        for instance in await self._instances.list():
            if instance.status is InstanceStatus.DISABLED:
                continue
            await self.poll(instance)

    async def poll(self, instance: Instance, *, force: bool = False) -> int | None:
        """Read the count and publish it when it changed (or when ``force``). Never raises."""
        if not force and not await self._store.set_if_absent(
            f"lock:apr-poll:{instance.id}", b"1", ttl=max(self._interval - 1, 1)
        ):
            return None
        if not force and await self._store.get(f"apr:disabled:{instance.id}") is not None:
            return None
        try:
            body = await self._instances.system_call(instance, "GET", "/approvals/count")
        except CapabilityDisabledError:
            await self._store.set(f"apr:disabled:{instance.id}", b"1", ttl=DISABLED_BACKOFF)
            return None
        except (AgentOSError, InstanceUnreachableError) as exc:
            log.debug("approvals.count_failed", instance=instance.id, error=str(exc))
            return None
        count = int(cast("dict[str, Any]", body).get("count") or 0) if isinstance(body, dict) else 0
        key = COUNT_KEY.format(instance=instance.id)
        previous = await self._store.get(key)
        await self._store.set(key, str(count).encode(), ttl=24 * 3600)
        if force or previous is None or int(previous) != count:
            await self._bus.publish(
                instance_channel(instance.id),
                RealtimeEvent("approvals.count", {"count": count}, instance_id=instance.id),
            )
        return count


async def current_count(store: EphemeralStore, instance_id: str) -> int | None:
    """The last count the poller saw (the SSE endpoint sends it when a tab connects)."""
    value = await store.get(COUNT_KEY.format(instance=instance_id))
    return int(value) if value is not None else None


async def run_poller(container: AsyncContainer, interval: float) -> None:
    """Background loop started by the module; each round gets a fresh request scope."""
    while True:
        try:
            async with container() as request:
                poller = await request.get(ApprovalsCountPoller)
                await poller.poll_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  (the loop must survive anything a round throws)
            log.warning("approvals.poller_round_failed", error=str(exc))
        await asyncio.sleep(interval)


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
