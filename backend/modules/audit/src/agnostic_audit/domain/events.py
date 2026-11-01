"""Audit events and their deterministic summaries. Pure Python."""

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
