"""The only import surface other modules may use: record audit events, and read recent ones for activity feeds.

``record`` joins the caller's unit of work (the request's database session), so the event commits or rolls back
with the change it describes. ``record_now`` commits on its own; use it for denials and failures, where there is
no change to commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from agnostic_audit.application.archive import Archives, VerifyChain
from agnostic_audit.application.ports import EventQuery, IngestCursorRepository, ObjectStoreError, UnitOfWork
from agnostic_audit.application.use_cases import ListEvents, RecordEvent
from agnostic_audit.domain.chain import ChainResult
from agnostic_audit.domain.events import ANONYMOUS, Actor, AuditEntry, AuditEvent, Decision, IngestedEntry
from agnostic_kernel.auth import SYSTEM_PRINCIPAL, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ServiceUnavailableError

__all__ = [
    "ANONYMOUS",
    "Actor",
    "ArchiveReport",
    "ArchivedMonthInfo",
    "AuditAdmin",
    "AuditAdminImpl",
    "AuditEntry",
    "AuditEvent",
    "AuditLog",
    "AuditLogImpl",
    "AuditReader",
    "AuditReaderImpl",
    "ChainResult",
    "Decision",
    "IngestCursors",
    "IngestCursorsImpl",
    "IngestStream",
    "IngestedEntry",
    "RestoredMonth",
    "actor_of",
]

type IngestStream = Literal["decisions", "audit"]


def actor_of(principal: Principal | None) -> Actor:
    if principal is None:
        return ANONYMOUS
    return Actor(kind=principal.kind, id=principal.id, display=principal.display_name)


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> str: ...
    async def record_now(self, entry: AuditEntry) -> str: ...
    async def ingest(self, entries: Sequence[IngestedEntry]) -> int:
        """Store events read from an AgentOS trail (``source="agentos"``), each ``source_event_id`` once.

        Commits on its own; returns how many were new.
        """
        ...


class AuditLogImpl:
    def __init__(self, record: RecordEvent) -> None:
        self._record = record

    async def record(self, entry: AuditEntry) -> str:
        return (await self._record.in_transaction(entry)).id

    async def record_now(self, entry: AuditEntry) -> str:
        return (await self._record.now(entry)).id

    async def ingest(self, entries: Sequence[IngestedEntry]) -> int:
        return await self._record.ingest(entries)


class IngestCursors(Protocol):
    """Where ingestion stopped reading an instance's trail (an opaque value chosen by the reader)."""

    async def get(self, instance_id: str, stream: IngestStream) -> str | None: ...
    async def save(self, instance_id: str, stream: IngestStream, cursor: str | None) -> None:
        """Commits."""
        ...


class IngestCursorsImpl:
    def __init__(self, cursors: IngestCursorRepository, uow: UnitOfWork) -> None:
        self._cursors = cursors
        self._uow = uow

    async def get(self, instance_id: str, stream: IngestStream) -> str | None:
        return await self._cursors.get(instance_id, stream)

    async def save(self, instance_id: str, stream: IngestStream, cursor: str | None) -> None:
        await self._cursors.set(instance_id, stream, cursor, utcnow())
        await self._uow.commit()


@dataclass(frozen=True, slots=True)
class RestoredMonth:
    month: str
    event_count: int
    restore_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ArchivedMonthInfo:
    month: str
    event_count: int
    bytes: int
    archived_at: datetime
    restore_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ArchiveReport:
    month: str
    ok: bool
    event_count: int
    chained: int
    problems: tuple[str, ...]


class AuditAdmin(Protocol):
    """Operator actions for the command line (run as the system, outside any request)."""

    async def verify(self, since: datetime | None = None, until: datetime | None = None) -> ChainResult: ...
    async def restore(self, month: str) -> RestoredMonth:
        """Re-import an archived month (``YYYY-MM``) for 7 days of searching."""
        ...

    async def archives(self) -> list[ArchivedMonthInfo]: ...
    async def verify_archive(self, month: str) -> ArchiveReport:
        """Download one archived month and check it against its manifest (nothing is restored)."""
        ...


class AuditAdminImpl:
    def __init__(self, verify: VerifyChain, archives: Archives, record: RecordEvent) -> None:
        self._verify = verify
        self._archives = archives
        self._record = record

    async def verify(self, since: datetime | None = None, until: datetime | None = None) -> ChainResult:
        return await self._verify(since, until)

    async def restore(self, month: str) -> RestoredMonth:
        try:
            restored = await self._archives.restore(month)
        except ObjectStoreError as exc:
            raise ServiceUnavailableError(f"The archive storage failed: {exc}") from exc
        _ = await self._record.now(
            AuditEntry(
                action="audit.restore",
                actor=actor_of(SYSTEM_PRINCIPAL),
                resource_kind="audit_archive",
                resource_id=month,
                resource_display=month,
                via="cli",
                fields={"month": month},
            )
        )
        return RestoredMonth(restored.month, restored.event_count, restored.restore_expires_at)

    async def archives(self) -> list[ArchivedMonthInfo]:
        return [
            ArchivedMonthInfo(item.month, item.event_count, item.bytes, item.archived_at, item.restore_expires_at)
            for item in await self._archives.list()
        ]

    async def verify_archive(self, month: str) -> ArchiveReport:
        try:
            check = await self._archives.verify(month)
        except ObjectStoreError as exc:
            raise ServiceUnavailableError(f"The archive storage failed: {exc}") from exc
        _ = await self._record.now(
            AuditEntry(
                action="audit.archive_verify",
                actor=actor_of(SYSTEM_PRINCIPAL),
                resource_kind="audit_archive",
                resource_id=month,
                resource_display=month,
                via="cli",
                decision="allowed" if check.ok else "denied",
                fields={"month": month, "result": "intact" if check.ok else "damaged"},
            )
        )
        return ArchiveReport(month, check.ok, check.event_count, check.chained, check.problems)


class AuditReader(Protocol):
    async def recent(
        self, *, instance_id: str | None = None, actions: Sequence[str] = (), limit: int = 10
    ) -> list[AuditEvent]:
        """Newest first; ``actions`` are exact names or prefixes ending in ``*``. Callers check ``audit:read``."""
        ...


class AuditReaderImpl:
    def __init__(self, list_events: ListEvents) -> None:
        self._list = list_events

    async def recent(
        self, *, instance_id: str | None = None, actions: Sequence[str] = (), limit: int = 10
    ) -> list[AuditEvent]:
        if not actions:
            return list((await self._list(EventQuery(instance_id=instance_id), limit, None)).items)
        found: list[AuditEvent] = []
        for action in actions:
            page = await self._list(EventQuery(instance_id=instance_id, action=action), limit, None)
            found.extend(page.items)
        found.sort(key=lambda event: (event.occurred_at, event.id), reverse=True)
        return found[:limit]
