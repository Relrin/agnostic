"""Ports of the audit module."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agnostic_audit.domain.events import AuditEvent, Decision


@dataclass(frozen=True, slots=True)
class EventQuery:
    actor_id: str | None = None
    action: str | None = None
    """Exact action, or a prefix ending in ``*`` (``gateway.*``)."""
    decision: Decision | None = None
    instance_id: str | None = None
    resource_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class AuditRepository(Protocol):
    async def add(self, event: AuditEvent) -> None:
        """Add to the caller's unit of work; the caller commits."""
        ...

    async def get(self, event_id: str) -> AuditEvent | None: ...
    async def list_page(
        self, query: EventQuery, limit: int, after: tuple[datetime, str] | None
    ) -> Sequence[AuditEvent]: ...


class StandaloneAuditWriter(Protocol):
    async def write(self, event: AuditEvent) -> None:
        """Write and commit in a transaction of its own (denials, failed sign-ins, gateway decisions)."""
        ...


class PartitionMaintenance(Protocol):
    async def ensure_partitions(self, now: datetime, months_ahead: int) -> list[str]: ...
    async def drop_expired(self, now: datetime, retention_days: int) -> list[str]: ...
