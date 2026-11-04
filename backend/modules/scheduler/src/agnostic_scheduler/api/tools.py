"""Assistant tools over schedules and their runs, read as the asking person."""

from __future__ import annotations

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip
from agnostic_scheduler.application.schedules import Schedules, ScheduleView
from agnostic_scheduler.domain.schedules import ScheduleRun

SCOPE = "schedules:read"
LOOKUP_LIMIT = 100


class SchedulesArgs(BaseModel):
    enabled: bool | None = Field(None, description="Only enabled (true) or disabled (false) schedules")
    name: str | None = Field(None, description="Only schedules whose name contains this text")


class ScheduleRunsArgs(BaseModel):
    schedule: str = Field(description="Schedule id or name, e.g. daily-brief")
    limit: int = Field(10, ge=1, le=25)


def schedule_source(call: ToolCall, view: ScheduleView) -> Source:
    name = view.raw.get("name") or view.id
    return Source("schedule", f"Schedule {name}", f"/i/{call.instance_slug}/scheduler?schedule={view.id}")


def _run(run: ScheduleRun) -> dict[str, object]:
    return {
        "id": run.id,
        "attempt": run.attempt,
        "status": run.status,
        "status_code": run.status_code,
        "error": clip(run.error),
        "triggered_at": run.triggered_at.isoformat() if run.triggered_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "run_id": run.run_id,
        "session_id": run.session_id,
        "paused_for_input": run.paused_for_input,
    }


def _schedule(view: ScheduleView) -> dict[str, object]:
    raw = view.raw
    return {
        "id": view.id,
        "name": raw.get("name"),
        "enabled": raw.get("enabled"),
        "cron": raw.get("cron_expr"),
        "when": view.description,
        "timezone": raw.get("timezone"),
        "target": f"{view.target.kind}:{view.target.id}" if view.target.id else view.target.kind,
        "next_run_at": raw.get("next_run_at"),
        "consecutive_failures": view.consecutive_failures,
        "recent_runs": [_run(run) for run in view.runs[:3]],
        "disabled_note": view.note.reason if view.note else None,
    }


async def list_schedules(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, SchedulesArgs)
    views, _ = await (await container.get(Schedules)).list(
        call.principal, call.instance_id, enabled=args.enabled, page=1, limit=LOOKUP_LIMIT
    )
    if args.name:
        views = [view for view in views if args.name.lower() in str(view.raw.get("name") or "").lower()]
    return ToolResult(
        {"schedules": [_schedule(view) for view in views]},
        [schedule_source(call, view) for view in views[:5]]
        or [Source("schedules", "Scheduler", f"/i/{call.instance_slug}/scheduler")],
    )


async def get_schedule_runs(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, ScheduleRunsArgs)
    schedules = await container.get(Schedules)
    views, _ = await schedules.list(call.principal, call.instance_id, enabled=None, page=1, limit=LOOKUP_LIMIT)
    wanted = args.schedule.strip().lower()
    view = next((v for v in views if v.id.lower() == wanted), None) or next(
        (v for v in views if str(v.raw.get("name") or "").lower() == wanted), None
    )
    if view is None:
        raise NotFoundError(f"No schedule named or with id {args.schedule!r}.")
    found = await schedules.runs(call.principal, call.instance_id, view.id, page=1, limit=args.limit)
    return ToolResult(
        {"schedule": _schedule(view), "total": found.total, "runs": [_run(run) for run in found.runs]},
        [schedule_source(call, view)],
    )


TOOLS = (
    ToolSpec(
        "list_schedules",
        "Cron schedules that start background runs: when they run, what they start, recent outcomes and failures.",
        list_schedules,
        SchedulesArgs,
        SCOPE,
    ),
    ToolSpec(
        "get_schedule_runs",
        "The latest runs of one schedule, newest first: status, error, retry attempt and the run/session they started.",
        get_schedule_runs,
        ScheduleRunsArgs,
        SCOPE,
    ),
)
