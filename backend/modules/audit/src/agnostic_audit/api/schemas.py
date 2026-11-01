"""Response bodies of ``/api/v1/audit``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from agnostic_audit.domain.events import AuditEvent


class ActorOut(BaseModel):
    kind: Literal["user", "service_account", "system", "anonymous"]
    id: str
    display: str


class AuditEventOut(BaseModel):
    id: str
    occurred_at: datetime
    request_id: str | None
    actor: ActorOut
    via: str
    ip: str | None
    client: str | None
    action: str
    resource_kind: str | None
    resource_id: str | None
    resource_display: str | None
    instance_id: str | None
    decision: Literal["allowed", "denied", "n_a"]
    scope_checked: str | None
    missing_scopes: list[str]
    response_status: int | None
    summary: str
    diff: dict[str, Any] | None
    links: dict[str, Any] | None
    source: Literal["control_plane", "agentos"]

    @classmethod
    def from_domain(cls, event: AuditEvent) -> AuditEventOut:
        return cls(
            id=event.id,
            occurred_at=event.occurred_at,
            request_id=event.request_id,
            actor=ActorOut(kind=event.actor.kind, id=event.actor.id, display=event.actor.display),
            via=event.via,
            ip=event.ip,
            client=event.client,
            action=event.action,
            resource_kind=event.resource_kind,
            resource_id=event.resource_id,
            resource_display=event.resource_display,
            instance_id=event.instance_id,
            decision=event.decision,
            scope_checked=event.scope_checked,
            missing_scopes=list(event.missing_scopes),
            response_status=event.response_status,
            summary=event.summary,
            diff=dict(event.diff) if event.diff is not None else None,
            links=dict(event.links) if event.links is not None else None,
            source=event.source,
        )


class AuditActionOut(BaseModel):
    action: str
    summary_template: str
