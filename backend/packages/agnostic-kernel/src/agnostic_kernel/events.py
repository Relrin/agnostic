"""Realtime events for browsers: publish on a channel, subscribe to several, replay what a reconnecting tab missed.

Channels: ``evt:user:{id}`` (one person), ``evt:org`` (everyone), ``evt:instance:{id}`` (everyone with
access to the instance). Redis pub/sub carries live events; a short Redis stream per channel keeps the last ~1000 for
15 minutes so ``Last-Event-ID`` reconnects can catch up. :class:`MemoryEventBus` keeps the same semantics in one
process.

Events are hints, never the source of truth: losing Redis costs live updates (the UI still refetches), not data.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

import orjson
from redis.asyncio import Redis
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError
from ulid import ULID

from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

ORG_CHANNEL = "evt:org"
REPLAY_LENGTH = 1000
REPLAY_TTL_SECONDS = 15 * 60


def user_channel(user_id: str) -> str:
    return f"evt:user:{user_id}"


def instance_channel(instance_id: str) -> str:
    return f"evt:instance:{instance_id}"


_last_id = ULID.from_int(0)


def _event_id() -> str:
    """Monotonic within the process, so two events in the same millisecond still replay in order."""
    global _last_id  # noqa: PLW0603
    candidate = ULID()
    if candidate <= _last_id:
        candidate = ULID.from_int(int(_last_id) + 1)
    _last_id = candidate
    return str(candidate)


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    type: str
    """``approvals.count``, ``approval.resolved``, ``access.changed``, …"""
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])
    instance_id: str | None = None
    id: str = field(default_factory=_event_id)
    """A ULID: sortable, so replay can return what came after a ``Last-Event-ID``."""

    def to_json(self) -> bytes:
        return orjson.dumps({"id": self.id, "type": self.type, "instance_id": self.instance_id, "data": self.data})

    @classmethod
    def from_json(cls, raw: bytes | str) -> RealtimeEvent:
        value = cast("dict[str, Any]", orjson.loads(raw))
        return cls(
            type=str(value["type"]),
            data=cast("dict[str, Any]", value.get("data") or {}),
            instance_id=value.get("instance_id"),
            id=str(value["id"]),
        )


class Subscription(Protocol):
    async def next(self, wait: float) -> tuple[str, RealtimeEvent] | None:
        """The next ``(channel, event)``, or ``None`` when nothing arrived within ``wait`` seconds."""
        ...

    async def close(self) -> None: ...


class EventBus(Protocol):
    async def publish(self, channel: str, event: RealtimeEvent) -> None:
        """Never raises: a lost event is a missed live update, not an error."""
        ...

    async def subscribe(self, channels: Sequence[str]) -> Subscription: ...
    async def replay(self, channels: Sequence[str], after_id: str) -> list[tuple[str, RealtimeEvent]]:
        """Events newer than ``after_id`` still kept for these channels, oldest first."""
        ...


# ---------------------------------------------------------------- in-process


class _MemorySubscription:
    def __init__(self, bus: MemoryEventBus, channels: Sequence[str]) -> None:
        self._bus = bus
        self.channels = tuple(channels)
        self.queue: asyncio.Queue[tuple[str, RealtimeEvent]] = asyncio.Queue(maxsize=1000)

    async def next(self, wait: float) -> tuple[str, RealtimeEvent] | None:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=wait)
        except TimeoutError:
            return None

    async def close(self) -> None:
        self._bus.unsubscribe(self)


class MemoryEventBus:
    """Single-process fan-out with a bounded replay buffer per channel."""

    def __init__(self, clock: _Clock | None = None) -> None:
        self._subscribers: set[_MemorySubscription] = set()
        self._history: dict[str, deque[tuple[float, RealtimeEvent]]] = {}
        self._clock = clock or time.monotonic

    async def publish(self, channel: str, event: RealtimeEvent) -> None:
        history = self._history.setdefault(channel, deque(maxlen=REPLAY_LENGTH))
        history.append((self._clock(), event))
        for subscriber in list(self._subscribers):
            if channel in subscriber.channels:
                with contextlib.suppress(asyncio.QueueFull):  # a stuck tab loses live updates, not the bus
                    subscriber.queue.put_nowait((channel, event))

    async def subscribe(self, channels: Sequence[str]) -> Subscription:
        subscription = _MemorySubscription(self, channels)
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: _MemorySubscription) -> None:
        self._subscribers.discard(subscription)

    async def replay(self, channels: Sequence[str], after_id: str) -> list[tuple[str, RealtimeEvent]]:
        horizon = self._clock() - REPLAY_TTL_SECONDS
        found = [
            (channel, event)
            for channel in channels
            for at, event in self._history.get(channel, ())
            if at >= horizon and event.id > after_id
        ]
        return sorted(found, key=lambda item: item[1].id)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class _Clock(Protocol):
    def __call__(self) -> float: ...


# ---------------------------------------------------------------- Redis


class _RedisSubscription:
    def __init__(self, pubsub: PubSub, prefix: str) -> None:
        self._pubsub = pubsub
        self._prefix = prefix

    async def next(self, wait: float) -> tuple[str, RealtimeEvent] | None:
        deadline = time.monotonic() + wait
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                raw = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                message = cast("dict[str, Any] | None", raw)
            except (RedisError, OSError) as exc:
                log.warning("events.subscription_failed", error=str(exc))
                await asyncio.sleep(min(remaining, 1.0))
                continue
            if message is None or message.get("type") != "message":
                continue
            channel = cast("bytes | str", message["channel"])
            name = channel.decode() if isinstance(channel, bytes) else channel
            try:
                return name.removeprefix(self._prefix), RealtimeEvent.from_json(cast("bytes", message["data"]))
            except orjson.JSONDecodeError, KeyError:
                continue
        return None

    async def close(self) -> None:
        with contextlib.suppress(RedisError, OSError):
            await self._pubsub.unsubscribe()  # pyright: ignore[reportUnknownMemberType]
            await self._pubsub.aclose()


class RedisEventBus:
    def __init__(self, redis: Redis, prefix: str = "agnostic:") -> None:
        self._redis = redis
        self._prefix = prefix

    def _stream(self, channel: str) -> str:
        return f"{self._prefix}stream:{channel}"

    async def publish(self, channel: str, event: RealtimeEvent) -> None:
        payload = event.to_json()
        stream = self._stream(channel)
        try:
            _ = await self._redis.xadd(stream, {"e": payload}, maxlen=REPLAY_LENGTH, approximate=True)  # pyright: ignore[reportUnknownMemberType]
            _ = await self._redis.expire(stream, REPLAY_TTL_SECONDS)  # pyright: ignore[reportUnknownMemberType]
            _ = await self._redis.publish(self._prefix + channel, payload)  # pyright: ignore[reportUnknownMemberType]
        except (RedisError, OSError) as exc:
            log.warning("events.publish_failed", channel=channel, type=event.type, error=str(exc))

    async def subscribe(self, channels: Sequence[str]) -> Subscription:
        pubsub = self._redis.pubsub()  # pyright: ignore[reportUnknownMemberType]
        await pubsub.subscribe(*(self._prefix + channel for channel in channels))  # pyright: ignore[reportUnknownMemberType]
        return _RedisSubscription(pubsub, self._prefix)

    async def replay(self, channels: Sequence[str], after_id: str) -> list[tuple[str, RealtimeEvent]]:
        found: list[tuple[str, RealtimeEvent]] = []
        for channel in channels:
            try:
                entries = await self._redis.xrange(self._stream(channel), count=REPLAY_LENGTH)  # pyright: ignore[reportUnknownMemberType]
            except (RedisError, OSError) as exc:
                log.warning("events.replay_failed", channel=channel, error=str(exc))
                continue
            for _, fields in cast("list[tuple[bytes, dict[bytes, bytes]]]", entries):
                raw = fields.get(b"e")
                if raw is None:
                    continue
                event = RealtimeEvent.from_json(raw)
                if event.id > after_id:
                    found.append((channel, event))
        return sorted(found, key=lambda item: item[1].id)
