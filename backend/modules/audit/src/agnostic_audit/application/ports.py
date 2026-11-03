"""Ports of the audit module."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agnostic_audit.domain.archive import ArchiveTarget
from agnostic_audit.domain.events import ActorKind, AuditEvent, Decision, Source
from agnostic_audit.domain.governance import ArchivedMonth, ExportJob, ExportStatus, SavedView
from agnostic_audit.domain.siem import DeliveryResult, Sink, SinkStatus

type Position = tuple[datetime, str]
"""``(occurred_at, id)``: a place in the log."""


@dataclass(frozen=True, slots=True)
class EventQuery:
    actor_id: str | None = None
    actor_kind: ActorKind | None = None
    action: str | None = None
    """Exact action, or a prefix ending in ``*`` (``gateway.*``)."""
    decision: Decision | None = None
    instance_id: str | None = None
    resource_id: str | None = None
    source: Source | None = None
    q: str | None = None
    """Case-insensitive text in the resource id or name, request id, IP or actor name."""
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActorSummary:
    kind: ActorKind
    id: str
    display: str
    count: int


class AuditRepository(Protocol):
    async def add(self, event: AuditEvent, *, chained: bool = False) -> AuditEvent:
        """Add to the caller's unit of work; the caller commits.

        With ``chained`` the event is linked into the hash chain (taking the chain lock until the caller commits);
        the stored event (its time, ``prev_hash`` and ``hash``) is returned.
        """
        ...

    async def get(self, event_id: str) -> AuditEvent | None: ...
    async def list_page(self, query: EventQuery, limit: int, after: Position | None) -> Sequence[AuditEvent]:
        """Newest first, strictly older than ``after``."""
        ...

    async def ascending(
        self, query: EventQuery, limit: int, after: Position | None, *, before: datetime | None = None
    ) -> Sequence[AuditEvent]:
        """Oldest first, strictly after ``after`` and (when given) strictly before ``before``."""
        ...

    async def count(self, query: EventQuery, cap: int) -> int:
        """Matching events, counting at most ``cap``."""
        ...

    async def actors(self, since: datetime, limit: int) -> list[ActorSummary]: ...
    async def latest_at(self) -> datetime | None: ...
    async def known_source_ids(self, source: Source, ids: Sequence[str]) -> set[str]: ...


class StandaloneAuditWriter(Protocol):
    async def write(self, event: AuditEvent, *, chained: bool = False) -> AuditEvent:
        """Write and commit in a transaction of its own (denials, failed sign-ins, gateway decisions)."""
        ...

    async def write_many(self, events: Sequence[AuditEvent], *, chained: bool = False) -> int:
        """Ingest: one transaction; events whose ``(source, source_event_id)`` is already stored are skipped."""
        ...


class PartitionMaintenance(Protocol):
    async def ensure_partitions(self, now: datetime, months_ahead: int) -> list[str]: ...
    async def drop_expired(self, now: datetime, retention_days: int) -> list[str]:
        """Drop (or, on SQLite, delete) every month past retention without archiving it."""
        ...

    async def expired_months(self, now: datetime, retention_days: int) -> list[str]:
        """``YYYY-MM`` of every stored month whose newest possible event is past retention, oldest first."""
        ...

    def month_events(self, month: str, batch: int = 1000) -> AsyncIterator[AuditEvent]:
        """The month's events in chain order (``occurred_at``, ``id``)."""
        ...

    async def month_count(self, month: str) -> int: ...
    async def drop_month(self, month: str) -> None: ...
    async def ensure_month(self, month: str) -> None:
        """Make sure events of ``month`` can be inserted into their own partition (PostgreSQL); no-op on SQLite."""
        ...

    async def insert_events(self, events: Sequence[AuditEvent]) -> None: ...


class PolicyStore(Protocol):
    async def load(self) -> tuple[dict[str, Any], str | None] | None:
        """The stored policy's columns and its sealed secret, or ``None`` before anyone saved one."""
        ...

    async def save(self, values: Mapping[str, Any], secret_enc: str | None) -> None: ...
    async def record_archive_run(self, at: datetime, error: str | None) -> None: ...


class ViewRepository(Protocol):
    async def visible_to(self, owner_id: str) -> list[SavedView]:
        """The person's own views and every shared view, by position then name."""
        ...

    async def get(self, view_id: str) -> SavedView | None: ...
    async def save(self, view: SavedView) -> None: ...
    async def delete(self, view_id: str) -> None: ...


class ExportRepository(Protocol):
    async def add(self, job: ExportJob) -> None: ...
    async def get(self, export_id: str) -> ExportJob | None: ...
    async def by_requester(self, requested_by: str, now: datetime) -> list[ExportJob]: ...
    async def set_status(
        self,
        export_id: str,
        status: ExportStatus,
        *,
        content: bytes | None = None,
        row_count: int | None = None,
        error: str | None = None,
    ) -> None: ...
    async def content(self, export_id: str) -> bytes | None: ...
    async def delete_expired(self, now: datetime) -> int: ...


class ArchiveRepository(Protocol):
    async def list(self) -> list[ArchivedMonth]: ...
    async def get(self, month: str) -> ArchivedMonth | None: ...
    async def save(self, archive: ArchivedMonth) -> None: ...


class SinkRepository(Protocol):
    async def list(self) -> list[Sink]: ...
    async def get(self, sink_id: str) -> Sink | None: ...
    async def save(self, sink: Sink) -> None: ...
    async def delete(self, sink_id: str) -> None: ...
    async def cursor(self, sink_id: str) -> Position | None: ...
    async def set_cursor(self, sink_id: str, position: Position) -> None: ...
    async def record_delivery(
        self,
        sink_id: str,
        *,
        status: SinkStatus,
        failure_count: int,
        last_error: str | None,
        last_event_at: datetime | None,
    ) -> None: ...


class IngestCursorRepository(Protocol):
    async def get(self, instance_id: str, stream: str) -> str | None: ...
    async def set(self, instance_id: str, stream: str, cursor: str | None, at: datetime) -> None: ...


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class ObjectStoreError(Exception):
    """The storage refused a request or couldn't be reached; the message is safe to show."""


class ObjectNotFoundError(ObjectStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    size: int
    etag: str | None


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str, retain_until: datetime | None = None) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def head(self, key: str) -> StoredObject: ...
    async def delete(self, key: str) -> None: ...


class ObjectStores(Protocol):
    def open(self, target: ArchiveTarget) -> ObjectStore: ...


class SinkTransport(Protocol):
    async def send(self, sink: Sink, events: Sequence[AuditEvent]) -> DeliveryResult:
        """Deliver one batch; never raises (failures come back in the result)."""
        ...


class DeliveryLock(Protocol):
    def hold(self) -> AbstractAsyncContextManager[bool]:
        """``True`` inside when this process may deliver now; ``False`` while another delivery runs."""
        ...


class Jobs(Protocol):
    async def defer(self, task_name: str, /, **kwargs: str) -> None: ...
    async def defer_once(self, task_name: str, *, delay_seconds: int) -> None:
        """Queue ``task_name`` unless it is already queued (a queueing lock), to run after a delay."""
        ...
