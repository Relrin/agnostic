"""``GET /api/v1/events``: one SSE stream per browser tab (the leader tab of each browser, really).

Permissions are computed when the stream opens. When anything access-related changes (the access generation in the
ephemeral store moves), the stream sends ``access.changed`` and ends; the browser refetches ``/me/access`` and
reconnects with ``Last-Event-ID``, which recomputes them.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from agnostic_access.facade import AccessFacade, satisfies
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import EphemeralStore, access_generation
from agnostic_kernel.events import ORG_CHANNEL, EventBus, instance_channel, user_channel
from agnostic_notifications.domain.events import HEARTBEAT, SCOPED_EVENTS, frame, visible


@dataclass(frozen=True, slots=True)
class StreamPlan:
    principal: Principal
    grants: Mapping[str, frozenset[str]]
    channels: tuple[str, ...]
    generation: str


class EventStream:
    def __init__(
        self,
        access: AccessFacade,
        instances: InstancesFacade,
        bus: EventBus,
        store: EphemeralStore,
    ) -> None:
        self._access = access
        self._instances = instances
        self._bus = bus
        self._store = store

    async def plan(self, principal: Principal) -> StreamPlan:
        """Which channels and instance-scoped events this person may receive (needs the database)."""
        grants: dict[str, frozenset[str]] = {}
        for instance in await self._instances.list():
            runtime = (await self._access.access(principal.id, instance.id)).runtime_scopes()
            if not runtime:
                continue
            grants[instance.id] = frozenset(
                scope for scope in set(SCOPED_EVENTS.values()) if any(satisfies(held, scope) for held in runtime)
            )
        channels = (user_channel(principal.id), ORG_CHANNEL, *(instance_channel(i) for i in sorted(grants)))
        return StreamPlan(principal, grants, channels, await access_generation(self._store))

    async def events(
        self, plan: StreamPlan, *, last_event_id: str | None, heartbeat: float, max_seconds: float
    ) -> AsyncIterator[bytes]:
        """The SSE body. Needs no database: call :meth:`plan` first, then release the session."""
        subscription = await self._bus.subscribe(plan.channels)
        try:
            yield frame(None, "ready", {"instances": sorted(plan.grants), "retry_ms": 3000})
            if last_event_id:
                for _, event in await self._bus.replay(plan.channels, last_event_id):
                    if visible(event.type, event.instance_id, plan.grants):
                        yield frame(event.id, event.type, {**event.data, "instance_id": event.instance_id})
            deadline = time.monotonic() + max_seconds
            while time.monotonic() < deadline:
                received = await subscription.next(heartbeat)
                if received is None:
                    if await access_generation(self._store) != plan.generation:
                        yield frame(None, "access.changed", {})
                        return
                    yield HEARTBEAT
                    continue
                _, event = received
                if visible(event.type, event.instance_id, plan.grants):
                    yield frame(event.id, event.type, {**event.data, "instance_id": event.instance_id})
        finally:
            await subscription.close()
