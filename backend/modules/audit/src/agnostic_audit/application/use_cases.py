"""Use cases of the audit module."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from agnostic_audit.application.ports import (
    AuditRepository,
    EventQuery,
    PartitionMaintenance,
    StandaloneAuditWriter,
)
from agnostic_audit.domain.events import EVENT_ID_PREFIX, AuditEntry, AuditEvent, render_summary
from agnostic_kernel.context import current_client, current_request_id
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import AuditActionDecl

log = get_logger(__name__)


class AuditVocabulary:
    """Every action declared by an enabled module, with its summary template."""

    def __init__(self, declarations: Iterable[AuditActionDecl]) -> None:
        self._templates: dict[str, str] = {decl.action: decl.summary_template for decl in declarations}

    def template(self, action: str) -> str | None:
        template = self._templates.get(action)
        if template is None:
            log.warning("audit.undeclared_action", action=action)
        return template

    def actions(self) -> Mapping[str, str]:
        return dict(self._templates)


def build_event(entry: AuditEntry, vocabulary: AuditVocabulary) -> AuditEvent:
    client = current_client()
    return AuditEvent(
        id=new_id(EVENT_ID_PREFIX),
        occurred_at=utcnow(),
        request_id=current_request_id(),
        actor=entry.actor,
        via=entry.via,
        ip=client.ip,
        client=client.user_agent,
        action=entry.action,
        resource_kind=entry.resource_kind,
        resource_id=entry.resource_id,
        resource_display=entry.resource_display,
        instance_id=entry.instance_id,
        decision=entry.decision,
        scope_checked=entry.scope_checked,
        missing_scopes=entry.missing_scopes,
        response_status=entry.response_status,
        summary=render_summary(vocabulary.template(entry.action), entry),
        diff=entry.diff,
        links=entry.links,
        source="control_plane",
    )


class RecordEvent:
    def __init__(
        self, repository: AuditRepository, standalone: StandaloneAuditWriter, vocabulary: AuditVocabulary
    ) -> None:
        self._repository = repository
        self._standalone = standalone
        self._vocabulary = vocabulary

    async def in_transaction(self, entry: AuditEntry) -> AuditEvent:
        event = build_event(entry, self._vocabulary)
        await self._repository.add(event)
        return event

    async def now(self, entry: AuditEntry) -> AuditEvent:
        event = build_event(entry, self._vocabulary)
        await self._standalone.write(event)
        return event


@dataclass(frozen=True, slots=True)
class EventPage:
    items: list[AuditEvent]
    next_after: AuditEvent | None


class ListEvents:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def __call__(self, query: EventQuery, limit: int, after: tuple[str, str] | None) -> EventPage:
        position = (datetime.fromisoformat(after[0]), after[1]) if after is not None else None
        rows = list(await self._repository.list_page(query, limit + 1, position))
        items = rows[:limit]
        return EventPage(items=items, next_after=items[-1] if len(rows) > limit and items else None)


class GetEvent:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def __call__(self, event_id: str) -> AuditEvent:
        event = await self._repository.get(event_id)
        if event is None:
            raise NotFoundError(f"Audit event {event_id} doesn't exist.")
        return event


class MaintainPartitions:
    def __init__(self, maintenance: PartitionMaintenance, retention_days: int, months_ahead: int = 2) -> None:
        self._maintenance = maintenance
        self._retention_days = retention_days
        self._months_ahead = months_ahead

    async def __call__(self) -> tuple[list[str], list[str]]:
        now = utcnow()
        created = await self._maintenance.ensure_partitions(now, self._months_ahead)
        dropped = await self._maintenance.drop_expired(now, self._retention_days)
        if created or dropped:
            log.info("audit.partitions", created=created, dropped=dropped)
        return created, dropped
