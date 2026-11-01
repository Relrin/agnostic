"""The only import surface other modules may use: record audit events, and read recent ones for activity feeds.

``record`` joins the caller's unit of work (the request's database session), so the event commits or rolls back
with the change it describes. ``record_now`` commits on its own; use it for denials and failures, where there is
no change to commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from agnostic_audit.application.ports import EventQuery
from agnostic_audit.application.use_cases import ListEvents, RecordEvent
from agnostic_audit.domain.events import ANONYMOUS, Actor, AuditEntry, AuditEvent, Decision
from agnostic_kernel.auth import Principal

__all__ = [
    "ANONYMOUS",
    "Actor",
    "AuditEntry",
    "AuditEvent",
    "AuditLog",
    "AuditLogImpl",
    "AuditReader",
    "AuditReaderImpl",
    "Decision",
    "actor_of",
]


def actor_of(principal: Principal | None) -> Actor:
    if principal is None:
        return ANONYMOUS
    return Actor(kind=principal.kind, id=principal.id, display=principal.display_name)


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> str: ...
    async def record_now(self, entry: AuditEntry) -> str: ...


class AuditLogImpl:
    def __init__(self, record: RecordEvent) -> None:
        self._record = record

    async def record(self, entry: AuditEntry) -> str:
        return (await self._record.in_transaction(entry)).id

    async def record_now(self, entry: AuditEntry) -> str:
        return (await self._record.now(entry)).id


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
