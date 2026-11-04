"""Assistant tool over the audit log. Needs ``audit:read`` on the control plane, like the Audit page."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_audit.application.ports import EventQuery
from agnostic_audit.application.use_cases import GetEvent, ListEvents
from agnostic_audit.domain.events import AuditEvent
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip

READ_SCOPE = "audit:read"
PAGE = "/access/audit"


class SearchAuditArgs(BaseModel):
    event_id: str | None = Field(None, description="One event, with its full change diff")
    q: str | None = Field(None, description="Text in the resource id or name, request id, IP or actor name")
    action: str | None = Field(None, description="Action, or a prefix ending in * (studio.*, access.binding.*)")
    actor: str | None = Field(None, description="Actor id (usr_…, sa:…, system)")
    decision: Literal["allowed", "denied", "n_a"] | None = None
    this_instance_only: bool = Field(default=False, description="Only events about the instance being asked about")
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(15, ge=1, le=30)


def event_source(event: AuditEvent) -> Source:
    return Source("audit", f"Audit · {event.action}", f"{PAGE}?event={event.id}")


def _event(event: AuditEvent, *, diff: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "id": event.id,
        "at": event.occurred_at.isoformat(),
        "action": event.action,
        "summary": event.summary,
        "actor": event.actor.display,
        "actor_id": event.actor.id,
        "resource": event.resource_display or event.resource_id,
        "instance_id": event.instance_id,
        "decision": event.decision,
        "missing_scopes": list(event.missing_scopes),
        "denial_reason": event.denial_reason,
        "source": event.source,
    }
    if diff and event.diff is not None:
        value["diff"] = clip(dict(event.diff), 4000)
    return value


async def search_audit(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, SearchAuditArgs)
    if args.event_id:
        event = await (await container.get(GetEvent))(args.event_id)
        return ToolResult({"events": [_event(event, diff=True)]}, [event_source(event)])
    query = EventQuery(
        actor_id=args.actor,
        action=args.action,
        decision=args.decision,
        instance_id=call.instance_id if args.this_instance_only else None,
        q=args.q,
        since=args.since,
        until=args.until,
    )
    page = await (await container.get(ListEvents))(query, args.limit, None)
    return ToolResult(
        {"events": [_event(event, diff=False) for event in page.items], "more": page.next_after is not None},
        [event_source(event) for event in page.items[:5]] or [Source("audit", "Audit log", PAGE)],
    )


TOOLS = (
    ToolSpec(
        "search_audit",
        "The audit log, newest first: who did what, when, to which resource, allowed or denied. "
        "Pass event_id for one event with its change diff.",
        search_audit,
        SearchAuditArgs,
        READ_SCOPE,
        org_scope=True,
    ),
)
