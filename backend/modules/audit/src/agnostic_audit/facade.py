"""The only import surface other modules may use: record audit events.

``record`` joins the caller's unit of work (the request's database session), so the event commits or rolls back
with the change it describes. ``record_now`` commits on its own; use it for denials and failures, where there is
no change to commit.
"""

from __future__ import annotations

from typing import Protocol

from agnostic_audit.application.use_cases import RecordEvent
from agnostic_audit.domain.events import ANONYMOUS, Actor, AuditEntry, Decision
from agnostic_kernel.auth import Principal

__all__ = ["ANONYMOUS", "Actor", "AuditEntry", "AuditLog", "AuditLogImpl", "Decision", "actor_of"]


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
