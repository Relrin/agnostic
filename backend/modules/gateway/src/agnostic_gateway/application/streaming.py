"""Streaming helpers: SSE heartbeats, request-size limits, and the per-instance circuit breaker."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

HEARTBEAT = b": keepalive\n\n"


async def with_heartbeats(source: AsyncIterator[bytes], interval: float) -> AsyncIterator[bytes]:  # noqa: C901
    """Pass SSE bytes through untouched, adding a comment line when the upstream is quiet for ``interval``.

    Heartbeats keep proxies and load balancers from closing idle streams. They're only inserted between
    events (after a blank line), never inside one.
    """
    queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue(maxsize=32)

    async def pump() -> None:
        try:
            async for chunk in source:
                await queue.put(chunk)
        except Exception as exc:  # noqa: BLE001  (handed to the consumer, which re-raises)
            await queue.put(exc)
        else:
            await queue.put(None)

    task = asyncio.create_task(pump())
    tail = b"\n\n"
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                if tail.endswith((b"\n\n", b"\r\n\r\n")):
                    yield HEARTBEAT
                continue
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            if item:
                tail = (tail + item)[-4:]
                yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class PayloadTooLargeError(Exception):
    pass


async def limited(source: AsyncIterator[bytes], max_bytes: int) -> AsyncIterator[bytes]:
    """Stream a request body through without buffering it, stopping past ``max_bytes``."""
    total = 0
    async for chunk in source:
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(f"the request body is larger than {max_bytes} bytes")
        yield chunk


@dataclass(slots=True)
class _Circuit:
    failures: int = 0
    open_until: float = 0.0


@dataclass(slots=True)
class CircuitBreaker:
    """Per-instance, per-process circuit breaker.

    After ``threshold`` consecutive connection failures, calls fail fast for ``cooldown`` seconds; then one request
    goes through to test the runtime again (half-open).
    """

    threshold: int = 5
    cooldown: float = 30.0
    _circuits: dict[str, _Circuit] = field(default_factory=dict[str, _Circuit])

    def retry_after(self, instance_id: str) -> float | None:
        circuit = self._circuits.get(instance_id)
        if circuit is None or circuit.failures < self.threshold:
            return None
        remaining = circuit.open_until - time.monotonic()
        if remaining <= 0:
            circuit.open_until = time.monotonic() + self.cooldown  # half-open: this request is the probe
            return None
        return remaining

    def success(self, instance_id: str) -> None:
        self._circuits.pop(instance_id, None)

    def failure(self, instance_id: str) -> None:
        circuit = self._circuits.setdefault(instance_id, _Circuit())
        circuit.failures += 1
        if circuit.failures >= self.threshold:
            circuit.open_until = time.monotonic() + self.cooldown
