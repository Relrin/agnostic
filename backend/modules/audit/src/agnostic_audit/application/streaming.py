"""SIEM streaming: sinks, at-least-once delivery behind a per-sink cursor, and stream health."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from agnostic_audit.application.ports import (
    AuditRepository,
    DeliveryLock,
    EventQuery,
    Jobs,
    SinkRepository,
    SinkTransport,
    UnitOfWork,
)
from agnostic_audit.domain.governance import SINK_ID_PREFIX
from agnostic_audit.domain.siem import (
    DeliveryResult,
    Sink,
    SinkConfigError,
    SinkFormat,
    SinkKind,
    after_delivery,
    merge_config,
    synthetic_event,
    validate_config,
)
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

DELIVER_TASK = "audit.deliver_sinks"
SINK_FAILING_EVENT = "audit.sink_failing"


class StreamTrigger:
    """Queues a delivery soon after events are written, so streaming is near-live without a job per event."""

    def __init__(
        self,
        jobs: Jobs,
        has_sinks: Callable[[], Awaitable[bool]],
        *,
        enabled: bool,
        delay_seconds: int,
        ttl: float = 30.0,
    ) -> None:
        self._jobs = jobs
        self._has_sinks = has_sinks
        self._enabled = enabled
        self._delay = delay_seconds
        self._ttl = ttl
        self._known: bool | None = None
        self._expires = 0.0

    def invalidate(self) -> None:
        self._known = None

    async def poke(self) -> None:
        """Never raises: the periodic delivery picks up whatever a lost trigger missed."""
        if not self._enabled:
            return
        try:
            if self._known is None or time.monotonic() >= self._expires:
                self._known = await self._has_sinks()
                self._expires = time.monotonic() + self._ttl
            if self._known:
                await self._jobs.defer_once(DELIVER_TASK, delay_seconds=self._delay)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit.stream_trigger_failed", error=str(exc))


@dataclass(frozen=True, slots=True)
class StreamStatus:
    streaming: bool
    sinks: list[Sink]
    last_event_at: datetime | None


class SinkService:
    def __init__(
        self,
        sinks: SinkRepository,
        uow: UnitOfWork,
        transport: SinkTransport,
        trigger: StreamTrigger,
    ) -> None:
        self._sinks = sinks
        self._uow = uow
        self._transport = transport
        self._trigger = trigger

    async def list(self) -> list[Sink]:
        return await self._sinks.list()

    async def get(self, sink_id: str) -> Sink:
        sink = await self._sinks.get(sink_id)
        if sink is None:
            raise NotFoundError(f"Sink {sink_id} doesn't exist.")
        return sink

    async def create(
        self,
        *,
        name: str,
        kind: SinkKind,
        sink_format: SinkFormat,
        config: Mapping[str, Any],
        enabled: bool,
        created_by: str,
    ) -> Sink:
        try:
            normalised = validate_config(kind, config)
        except SinkConfigError as exc:
            raise ValidationFailedError(str(exc)) from exc
        now = utcnow()
        sink = Sink(
            id=new_id(SINK_ID_PREFIX),
            name=name,
            kind=kind,
            format=sink_format,
            config=normalised,
            enabled=enabled,
            status="ok" if enabled else "paused",
            failure_count=0,
            last_event_at=None,
            last_error=None,
            created_by=created_by,
            created_at=now,
        )
        await self._sinks.save(sink)
        # A new sink streams what happens from now on; it doesn't replay the log's history.
        await self._sinks.set_cursor(sink.id, (now, ""))
        await self._uow.commit()
        self._trigger.invalidate()
        return sink

    async def update(self, sink_id: str, changes: Mapping[str, Any]) -> tuple[Sink, Sink]:
        before = await self.get(sink_id)
        after = before
        if "name" in changes:
            after = replace(after, name=str(changes["name"]))
        if "format" in changes:
            after = replace(after, format=changes["format"])
        if "config" in changes:
            try:
                config = validate_config(after.kind, merge_config(before.config, changes["config"]))
            except SinkConfigError as exc:
                raise ValidationFailedError(str(exc)) from exc
            after = replace(after, config=config)
        if "enabled" in changes:
            enabled = bool(changes["enabled"])
            after = replace(after, enabled=enabled, status="ok" if enabled else "paused", failure_count=0)
        await self._sinks.save(after)
        await self._uow.commit()
        self._trigger.invalidate()
        return before, after

    async def delete(self, sink_id: str) -> Sink:
        sink = await self.get(sink_id)
        await self._sinks.delete(sink_id)
        await self._uow.commit()
        self._trigger.invalidate()
        return sink

    async def test(self, sink_id: str, *, actor_id: str, actor_display: str) -> DeliveryResult:
        sink = await self.get(sink_id)
        return await self._transport.send(sink, [synthetic_event(utcnow(), actor_id, actor_display)])

    async def status(self) -> StreamStatus:
        sinks = await self._sinks.list()
        active = [sink for sink in sinks if sink.enabled]
        times = [sink.last_event_at for sink in sinks if sink.last_event_at is not None]
        return StreamStatus(
            streaming=any(sink.status == "ok" for sink in active),
            sinks=sinks,
            last_event_at=max(times) if times else None,
        )


class DeliverSinks:
    """Send every enabled sink the events after its cursor, in order, in batches.

    Events younger than the settle window wait for the next run, so a transaction that commits a little late can't
    slip in behind the cursor. The cursor moves only after the sink accepted a batch: a crash or a failed request
    re-sends that batch next time (at-least-once).
    """

    def __init__(
        self,
        sinks: SinkRepository,
        events: AuditRepository,
        transport: SinkTransport,
        lock: DeliveryLock,
        uow: UnitOfWork,
        domain_events: DomainEvents,
        *,
        settle_seconds: float,
        batch_size: int,
        max_batches: int = 20,
    ) -> None:
        self._sinks = sinks
        self._events = events
        self._transport = transport
        self._lock = lock
        self._uow = uow
        self._domain_events = domain_events
        self._settle = timedelta(seconds=settle_seconds)
        self._batch = batch_size
        self._max_batches = max_batches

    async def __call__(self, now: datetime | None = None) -> dict[str, int]:
        delivered: dict[str, int] = {}
        async with self._lock.hold() as acquired:
            if not acquired:
                return delivered
            before = (now or utcnow()) - self._settle
            for sink in await self._sinks.list():
                if sink.enabled and sink.status != "paused":
                    delivered[sink.id] = await self._deliver(sink, before)
        return delivered

    async def _deliver(self, sink: Sink, before: datetime) -> int:
        sent = 0
        position = await self._sinks.cursor(sink.id)
        for _ in range(self._max_batches):
            batch = list(await self._events.ascending(EventQuery(), self._batch, position, before=before))
            if not batch:
                break
            result = await self._transport.send(sink, batch)
            health = after_delivery(sink, result)
            last = batch[-1]
            if result.ok:
                position = (last.occurred_at, last.id)
                await self._sinks.set_cursor(sink.id, position)
                sent += len(batch)
            await self._sinks.record_delivery(
                sink.id,
                status=health.status,
                failure_count=health.failure_count,
                last_error=health.last_error,
                last_event_at=last.occurred_at if result.ok else sink.last_event_at,
            )
            await self._uow.commit()
            sink = replace(
                sink,
                status=health.status,
                failure_count=health.failure_count,
                last_error=health.last_error,
                last_event_at=last.occurred_at if result.ok else sink.last_event_at,
            )
            if health.announce:
                await self._domain_events.publish(
                    SINK_FAILING_EVENT, {"sink_id": sink.id, "name": sink.name, "error": health.last_error}
                )
            if not result.ok:
                log.warning("audit.sink_delivery_failed", sink=sink.id, error=health.last_error)
                break
            if len(batch) < self._batch:
                break
        return sent
