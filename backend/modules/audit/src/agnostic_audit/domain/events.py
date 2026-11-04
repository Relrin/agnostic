"""Audit events and their deterministic summaries. No I/O."""

from __future__ import annotations

import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

EVENT_ID_PREFIX = "evt"

type Decision = Literal["allowed", "denied", "n_a"]
type ActorKind = Literal["user", "service_account", "system", "anonymous"]
type Source = Literal["control_plane", "agentos"]


@dataclass(frozen=True, slots=True)
class Actor:
    kind: ActorKind
    id: str
    display: str


ANONYMOUS = Actor(kind="anonymous", id="anonymous", display="Someone")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """What a module records. Context (request id, IP, client, time) is filled in by the audit log."""

    action: str
    actor: Actor
    resource_kind: str | None = None
    resource_id: str | None = None
    resource_display: str | None = None
    instance_id: str | None = None
    decision: Decision = "n_a"
    scope_checked: str | None = None
    missing_scopes: tuple[str, ...] = ()
    response_status: int | None = None
    fields: Mapping[str, str] = field(default_factory=dict[str, str])
    """Values for the action's summary template (``{actor}`` and ``{resource}`` are always available)."""
    diff: Mapping[str, Any] | None = None
    links: Mapping[str, Any] | None = None
    via: str = "web"
    summary: str | None = None
    """Overrides the template when the caller already has the sentence."""
    denial_reason: str | None = None
    """Why a denied decision was denied, in a sentence (shown in the event's detail)."""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    occurred_at: datetime
    request_id: str | None
    actor: Actor
    via: str
    ip: str | None
    client: str | None
    action: str
    resource_kind: str | None
    resource_id: str | None
    resource_display: str | None
    instance_id: str | None
    decision: Decision
    scope_checked: str | None
    missing_scopes: tuple[str, ...]
    response_status: int | None
    summary: str
    diff: Mapping[str, Any] | None
    links: Mapping[str, Any] | None
    source: Source
    denial_reason: str | None = None
    source_event_id: str | None = None
    """The event's id in the system it was ingested from (AgentOS); ``None`` for control-plane events."""
    prev_hash: str | None = None
    hash: str | None = None
    """Tamper-evidence chain (``None`` while the chain is off)."""


@dataclass(frozen=True, slots=True)
class IngestedEntry:
    """An event read from another system (an AgentOS decision or change trail) to store as-is."""

    source_event_id: str
    occurred_at: datetime
    action: str
    actor: Actor
    summary: str
    via: str = "agentos"
    resource_kind: str | None = None
    resource_id: str | None = None
    resource_display: str | None = None
    instance_id: str | None = None
    decision: Decision = "n_a"
    scope_checked: str | None = None
    missing_scopes: tuple[str, ...] = ()
    response_status: int | None = None
    denial_reason: str | None = None
    diff: Mapping[str, Any] | None = None
    client: str | None = None


class _Missing(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_summary(template: str | None, entry: AuditEntry) -> str:
    """Fill a template like ``"{actor} invited {email}"``; unknown placeholders stay visible instead of failing."""
    if entry.summary:
        return entry.summary
    values = _Missing(entry.fields)
    values.setdefault("actor", entry.actor.display)
    values.setdefault("resource", entry.resource_display or entry.resource_id or "")
    if template is None:
        return f"{entry.actor.display}: {entry.action}" + (f" {values['resource']}" if values["resource"] else "")
    return string.Formatter().vformat(template, (), values)


def can_request_access(event: AuditEvent) -> bool:
    """A person denied a scope on an instance can ask for temporary access to it."""
    return (
        event.decision == "denied"
        and event.actor.kind == "user"
        and event.instance_id is not None
        and bool(event.missing_scopes or event.scope_checked)
    )


def month_start(moment: datetime) -> datetime:
    moment = moment.astimezone(UTC)
    return datetime(moment.year, moment.month, 1, tzinfo=UTC)


def next_month(start: datetime) -> datetime:
    return datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=UTC)  # noqa: PLR2004


def partition_name(start: datetime) -> str:
    return f"audit_events_y{start.year:04d}m{start.month:02d}"


def partitions_to_create(now: datetime, months_ahead: int) -> list[tuple[str, datetime, datetime]]:
    """Current month plus ``months_ahead`` months: ``(name, from, to)``."""
    result: list[tuple[str, datetime, datetime]] = []
    start = month_start(now)
    for _ in range(months_ahead + 1):
        end = next_month(start)
        result.append((partition_name(start), start, end))
        start = end
    return result


def partition_expired(upper_bound: datetime, now: datetime, retention_days: int) -> bool:
    """A month can go once its *newest* possible event is older than the retention window."""
    return upper_bound <= now - timedelta(days=retention_days)


def iso_utc(moment: datetime) -> str:
    """``2026-10-31T17:04:12.381000Z``: microseconds always present, so the text round-trips exactly."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def event_document(event: AuditEvent) -> dict[str, Any]:
    """The event as a JSON-ready document: exports, archives and the JSON SIEM format share this shape."""
    return {
        "id": event.id,
        "occurred_at": iso_utc(event.occurred_at),
        "request_id": event.request_id,
        "actor": {"kind": event.actor.kind, "id": event.actor.id, "display": event.actor.display},
        "via": event.via,
        "ip": event.ip,
        "client": event.client,
        "action": event.action,
        "resource_kind": event.resource_kind,
        "resource_id": event.resource_id,
        "resource_display": event.resource_display,
        "instance_id": event.instance_id,
        "decision": event.decision,
        "scope_checked": event.scope_checked,
        "missing_scopes": list(event.missing_scopes),
        "response_status": event.response_status,
        "summary": event.summary,
        "denial_reason": event.denial_reason,
        "diff": dict(event.diff) if event.diff is not None else None,
        "links": dict(event.links) if event.links is not None else None,
        "source": event.source,
        "source_event_id": event.source_event_id,
        "prev_hash": event.prev_hash,
        "hash": event.hash,
    }


def event_from_document(document: Mapping[str, Any]) -> AuditEvent:
    """Inverse of :func:`event_document` (restoring an archive). Raises ``KeyError``/``ValueError`` when malformed."""
    actor = document["actor"]
    return AuditEvent(
        id=str(document["id"]),
        occurred_at=datetime.fromisoformat(str(document["occurred_at"])),
        request_id=document.get("request_id"),
        actor=Actor(kind=actor["kind"], id=str(actor["id"]), display=str(actor["display"])),
        via=str(document["via"]),
        ip=document.get("ip"),
        client=document.get("client"),
        action=str(document["action"]),
        resource_kind=document.get("resource_kind"),
        resource_id=document.get("resource_id"),
        resource_display=document.get("resource_display"),
        instance_id=document.get("instance_id"),
        decision=document["decision"],
        scope_checked=document.get("scope_checked"),
        missing_scopes=tuple(document.get("missing_scopes") or ()),
        response_status=document.get("response_status"),
        summary=str(document["summary"]),
        diff=document.get("diff"),
        links=document.get("links"),
        source=document["source"],
        denial_reason=document.get("denial_reason"),
        source_event_id=document.get("source_event_id"),
        prev_hash=document.get("prev_hash"),
        hash=document.get("hash"),
    )
