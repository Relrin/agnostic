"""Answer events over the kernel event bus (Redis streams with replay, or in-process with SQLite)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from agnostic_assistant.application.ports import RelayedEvent
from agnostic_assistant.domain.events import channel
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus, RealtimeEvent

CANCEL_TTL_SECONDS = 3600


class BusRelay:
    def __init__(self, bus: EventBus, store: EphemeralStore) -> None:
        self._bus = bus
        self._store = store

    async def publish(self, message_id: str, event_type: str, data: Mapping[str, Any]) -> None:
        await self._bus.publish(channel(message_id), RealtimeEvent(event_type, dict(data)))

    async def follow(self, message_id: str, after_id: str | None, wait: float) -> AsyncIterator[RelayedEvent | None]:
        name = channel(message_id)
        subscription = await self._bus.subscribe([name])
        try:
            last = after_id or ""
            for _, event in await self._bus.replay([name], last):
                last = event.id
                yield RelayedEvent(event.id, event.type, event.data)
            while True:
                received = await subscription.next(wait)
                if received is None:
                    yield None
                    continue
                _, event = received
                if event.id <= last:
                    continue
                last = event.id
                yield RelayedEvent(event.id, event.type, event.data)
        finally:
            await subscription.close()

    async def request_cancel(self, message_id: str) -> None:
        await self._store.set(f"asst:cancel:{message_id}", b"1", ttl=CANCEL_TTL_SECONDS)

    async def cancel_requested(self, message_id: str) -> bool:
        return await self._store.get(f"asst:cancel:{message_id}") is not None
