"""``GET /agnostic/v1/events``: new approvals and failed schedule runs since a point in time.

The control plane learns about both by listing ``/approvals`` and each schedule's runs on a timer. This route answers
"what happened since ``since``" in one call, so it can poll often and cheaply and react sooner:

- ``approval.created``: approvals created after ``since``; ``data`` is the approval as ``GET /approvals`` lists it.
- ``schedule_run.failed``: schedule runs that ended ``failed`` after ``since`` (completion time, else creation).

Events come oldest first, at most ``limit`` of them; pass ``next_since`` back as ``since`` for the next page. A page
never ends inside a second, since the next one starts after it: it stops before that second, or, when the second
alone overflows ``limit``, takes the whole second.

- **Access**: ``approvals:read`` and ``schedules:read`` (:data:`~agnostic_bridge.SCOPE_MAPPINGS`). Under user
  isolation a non-admin caller only sees their own approvals and schedule runs, as on the AgentOS routes.
- **Backends**: the OS db's approval and schedule methods, sync or async. A db without one of them contributes no
  events of that type.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.approvals.schema import ApprovalResponse
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from agnostic_bridge._files import _db_call

if TYPE_CHECKING:
    from agno.os import AgentOS

EVENTS_PATH = "/events"

EventType = Literal["approval.created", "schedule_run.failed"]

_PAGE_SIZE = 500
_FAILED_RUN_STATUSES = {"failed", "error", "timeout"}
_SCHEDULE_RUN_FIELDS = (
    "id",
    "schedule_id",
    "run_id",
    "session_id",
    "status",
    "error",
    "attempt",
    "triggered_at",
    "completed_at",
)
# Runs are listed by creation time but reported by completion time: keep reading a schedule's runs this far past
# ``since`` (its timeout, plus slack for retries and the poller) so a long run that failed after ``since`` is seen.
_DEFAULT_RUN_TIMEOUT_SECONDS = 3600
_RUN_SLACK_SECONDS = 600


class BridgeEvent(BaseModel):
    id: str = Field(description="'<type>:<source id>'; stable across polls")
    type: EventType
    at: int = Field(description="When it happened, epoch seconds")
    data: dict[str, Any]


class EventsResponse(BaseModel):
    events: list[BridgeEvent] = Field(description="Oldest first")
    next_since: int = Field(description="Pass back as since: the last event's at, or since when there are none")


def _epoch(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    return None


def _row(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if isinstance(item, BaseModel):
        return item.model_dump()
    return dict(getattr(item, "__dict__", {}))


async def _pages(db: BaseDb | AsyncBaseDb, method: str, **kwargs: Any) -> AsyncIterator[list[dict[str, Any]]]:
    """``(rows, total)`` pages of a list method, newest first; nothing when the db doesn't implement it."""
    if not callable(getattr(db, method, None)):
        return
    page = 1
    while True:
        try:
            result = await _db_call(db, method, limit=_PAGE_SIZE, page=page, **kwargs)
        except NotImplementedError:
            return
        rows = [_row(item) for item in (result[0] if isinstance(result, tuple) else result) or []]
        yield rows
        if len(rows) < _PAGE_SIZE:
            return
        page += 1


def _approval_data(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return ApprovalResponse.model_validate(row).model_dump(mode="json")
    except ValidationError:  # a row the AgentOS schema rejects still reports what it has
        return {name: row.get(name) for name in ApprovalResponse.model_fields}


async def approval_events(db: BaseDb | AsyncBaseDb, since: int, user_id: str | None) -> list[BridgeEvent]:
    events: list[BridgeEvent] = []
    async for rows in _pages(db, "get_approvals", user_id=user_id):
        created = [(_epoch(row.get("created_at")), row) for row in rows]
        for at, row in created:
            if at is not None and at > since:
                events.append(
                    BridgeEvent(
                        id=f"approval.created:{row.get('id')}", type="approval.created", at=at, data=_approval_data(row)
                    )
                )
        if any(at is not None and at <= since for at, _ in created):  # newest first: the rest is older
            break
    return events


async def schedule_run_events(db: BaseDb | AsyncBaseDb, since: int, user_id: str | None) -> list[BridgeEvent]:
    if not callable(getattr(db, "get_schedule_runs", None)):
        return []
    schedules: list[dict[str, Any]] = []
    async for rows in _pages(db, "get_schedules", user_id=user_id):
        schedules.extend(rows)

    events: list[BridgeEvent] = []
    for schedule in schedules:
        timeout = _epoch(schedule.get("timeout_seconds")) or _DEFAULT_RUN_TIMEOUT_SECONDS
        floor = since - timeout - _RUN_SLACK_SECONDS
        async for rows in _pages(db, "get_schedule_runs", schedule_id=schedule.get("id"), user_id=user_id):
            for row in rows:
                if str(row.get("status") or "").lower() not in _FAILED_RUN_STATUSES:
                    continue
                at = _epoch(row.get("completed_at")) or _epoch(row.get("created_at"))
                if at is not None and at > since:
                    data = {name: row.get(name) for name in _SCHEDULE_RUN_FIELDS}
                    events.append(
                        BridgeEvent(
                            id=f"schedule_run.failed:{row.get('id')}", type="schedule_run.failed", at=at, data=data
                        )
                    )
            if any((_epoch(row.get("created_at")) or 0) <= floor for row in rows):
                break
    return events


def page_of(events: list[BridgeEvent], limit: int) -> list[BridgeEvent]:
    """The oldest ``limit`` events, without splitting the second the page ends in."""
    events = sorted(events, key=lambda event: (event.at, event.id))
    if len(events) <= limit or events[limit].at != events[limit - 1].at:
        return events[:limit]
    last = events[limit - 1].at
    start = next(index for index, event in enumerate(events) if event.at == last)
    if start > 0:
        return events[:start]
    return [event for event in events if event.at == last]


def add_event_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.get(
        EVENTS_PATH,
        operation_id="agnostic_bridge_list_events",
        summary="New approvals and failed schedule runs",
        description=(
            "Approvals created and schedule runs failed after since (epoch seconds), oldest first; pass next_since "
            "back as since. Needs approvals:read and schedules:read; isolated callers see their own rows only."
        ),
        response_model=EventsResponse,
        responses={503: {"description": "The AgentOS has no db, so no approvals or schedules"}},
    )
    async def list_events(
        request: Request,
        since: int = Query(0, ge=0, description="Only events after this time, epoch seconds"),
        limit: int = Query(100, ge=1, le=500, description="Most events to return"),
    ) -> EventsResponse:
        db = agent_os.db
        if not isinstance(db, (BaseDb, AsyncBaseDb)):
            raise HTTPException(status_code=503, detail="This AgentOS has no db, so no approvals or schedules")
        user_id = get_scoped_user_id(request)
        events = await approval_events(db, since, user_id) + await schedule_run_events(db, since, user_id)
        page = page_of(events, limit)
        return EventsResponse(events=page, next_since=page[-1].at if page else since)
