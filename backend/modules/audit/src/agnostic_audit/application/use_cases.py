"""Use cases of the audit module."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from agnostic_audit.application.policy import PolicyCache
from agnostic_audit.application.ports import (
    ActorSummary,
    AuditRepository,
    EventQuery,
    StandaloneAuditWriter,
)
from agnostic_audit.application.streaming import StreamTrigger
from agnostic_audit.domain.events import (
    EVENT_ID_PREFIX,
    AuditEntry,
    AuditEvent,
    IngestedEntry,
    render_summary,
)
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
        denial_reason=entry.denial_reason,
    )


def ingested_event(entry: IngestedEntry) -> AuditEvent:
    return AuditEvent(
        id=new_id(EVENT_ID_PREFIX),
        occurred_at=entry.occurred_at,
        request_id=None,
        actor=entry.actor,
        via=entry.via,
        ip=None,
        client=entry.client,
        action=entry.action,
        resource_kind=entry.resource_kind,
        resource_id=entry.resource_id,
        resource_display=entry.resource_display,
        instance_id=entry.instance_id,
        decision=entry.decision,
        scope_checked=entry.scope_checked,
        missing_scopes=entry.missing_scopes,
        response_status=entry.response_status,
        summary=entry.summary,
        diff=entry.diff,
        links=None,
        source="agentos",
        denial_reason=entry.denial_reason,
        source_event_id=entry.source_event_id,
    )


class RecordEvent:
    """Writes control-plane events; links them into the hash chain while the policy has it on."""

    def __init__(
        self,
        repository: AuditRepository,
        standalone: StandaloneAuditWriter,
        vocabulary: AuditVocabulary,
        policy: PolicyCache,
        stream: StreamTrigger,
    ) -> None:
        self._repository = repository
        self._standalone = standalone
        self._vocabulary = vocabulary
        self._policy = policy
        self._stream = stream

    async def in_transaction(self, entry: AuditEntry) -> AuditEvent:
        event = build_event(entry, self._vocabulary)
        stored = await self._repository.add(event, chained=(await self._policy.get()).hash_chain)
        await self._stream.poke()
        return stored

    async def now(self, entry: AuditEntry) -> AuditEvent:
        event = build_event(entry, self._vocabulary)
        stored = await self._standalone.write(event, chained=(await self._policy.get()).hash_chain)
        await self._stream.poke()
        return stored

    async def ingest(self, entries: Sequence[IngestedEntry]) -> int:
        """Store events read from AgentOS once each (by ``source_event_id``); returns how many were new.

        Ingested events keep the time they happened elsewhere, so they stay outside the hash chain (which orders
        events by when the control plane wrote them); the runtime's own trail is their source of truth.
        """
        if not entries:
            return 0
        written = await self._standalone.write_many([ingested_event(entry) for entry in entries])
        if written:
            await self._stream.poke()
        return written


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


class ListActors:
    """People and machines seen in the log recently, most active first (for the actor filter)."""

    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def __call__(self, days: int = 90, limit: int = 100) -> list[ActorSummary]:
        return await self._repository.actors(utcnow() - timedelta(days=days), limit)
