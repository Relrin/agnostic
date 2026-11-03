"""Request and response bodies of ``/api/v1/instances/{instance}/schedules``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_scheduler.application.schedules import EndpointCheck, SchedulerStatus, ScheduleView
from agnostic_scheduler.domain.cron import Preview
from agnostic_scheduler.domain.schedules import ScheduleRun, parse_time

type TargetKindName = Literal["agent", "team", "workflow", "custom"]
type Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class ScheduleRunOut(BaseModel):
    id: str
    schedule_id: str
    attempt: int
    status: str
    states: list[str] = Field(description="Badges in order, e.g. PAUSED then COMPLETED")
    attempt_label: str
    status_code: int | None
    run_id: str | None
    session_id: str | None
    error: str | None
    triggered_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None

    @classmethod
    def of(cls, run: ScheduleRun, max_retries: int = 0) -> ScheduleRunOut:
        return cls(
            id=run.id,
            schedule_id=run.schedule_id,
            attempt=run.attempt,
            status=run.status,
            states=run.states,
            attempt_label=run.attempt_label(max_retries),
            status_code=run.status_code,
            run_id=run.run_id,
            session_id=run.session_id,
            error=run.error,
            triggered_at=run.triggered_at,
            completed_at=run.completed_at,
            duration_seconds=run.duration_seconds,
        )


class DisabledNoteOut(BaseModel):
    reason: str
    by: str
    by_name: str
    at: datetime


class ScheduleOut(BaseModel):
    id: str
    name: str
    description: str | None
    method: str
    endpoint: str
    payload: dict[str, Any] | None
    cron_expr: str | None
    timezone: str
    human: str | None = Field(description="The cron expression as a sentence")
    timeout_seconds: int | None
    max_retries: int
    retry_delay_seconds: int | None
    enabled: bool
    next_run_at: datetime | None
    target_kind: TargetKindName
    target_id: str | None
    disabled_reason: str | None = Field(description="Set by AgentOS (e.g. the target was archived)")
    disabled_note: DisabledNoteOut | None = Field(description="Why a person disabled it")
    user_id: str | None
    managed_by: str | None
    created_at: datetime | None
    updated_at: datetime | None
    last_runs: list[ScheduleRunOut]
    consecutive_failures: int

    @classmethod
    def of(cls, view: ScheduleView) -> ScheduleOut:
        raw = view.raw
        retries = int(raw.get("max_retries") or 0)
        note = view.note
        payload = raw.get("payload")
        return cls(
            id=view.id,
            name=view.name,
            description=raw.get("description"),
            method=str(raw.get("method") or "POST"),
            endpoint=str(raw.get("endpoint") or ""),
            payload=payload if isinstance(payload, dict) else None,  # pyright: ignore[reportUnknownArgumentType]
            cron_expr=raw.get("cron_expr") or None,
            timezone=str(raw.get("timezone") or "UTC"),
            human=view.description,
            timeout_seconds=raw.get("timeout_seconds"),
            max_retries=retries,
            retry_delay_seconds=raw.get("retry_delay_seconds"),
            enabled=bool(raw.get("enabled")),
            next_run_at=parse_time(raw.get("next_run_at")),
            target_kind=view.target.kind,
            target_id=view.target.id,
            disabled_reason=raw.get("disabled_reason"),
            disabled_note=DisabledNoteOut(
                reason=note.reason, by=note.disabled_by, by_name=note.disabled_by_name, at=note.disabled_at
            )
            if note
            else None,
            user_id=raw.get("user_id"),
            managed_by=raw.get("managed_by"),
            created_at=parse_time(raw.get("created_at")),
            updated_at=parse_time(raw.get("updated_at")),
            last_runs=[ScheduleRunOut.of(run, retries) for run in view.runs],
            consecutive_failures=view.consecutive_failures,
        )


class SchedulesPageOut(BaseModel):
    data: list[ScheduleOut]
    page: int
    limit: int
    total: int | None


class RunsPageOut(BaseModel):
    data: list[ScheduleRunOut]
    page: int
    limit: int
    total: int | None


class ScheduleIn(BaseModel):
    name: str = Field(max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$")
    description: str | None = Field(default=None, max_length=2000)
    cron_expr: str = Field(default="", max_length=120, description="5-field cron; empty runs only when triggered")
    timezone: str = Field(default="UTC", max_length=64)
    method: Method = "POST"
    endpoint: str = Field(max_length=512, pattern=r"^/[^\s]*$", examples=["/agents/billing-agent/runs"])
    payload: dict[str, Any] | None = None
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_delay_seconds: int = Field(default=60, ge=1, le=3600)


class SchedulePatch(BaseModel):
    name: str | None = Field(default=None, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$")
    description: str | None = Field(default=None, max_length=2000)
    cron_expr: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    method: Method | None = None
    endpoint: str | None = Field(default=None, max_length=512, pattern=r"^/[^\s]*$")
    payload: dict[str, Any] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_delay_seconds: int | None = Field(default=None, ge=1, le=3600)


class DisableIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500, description="Shown next to the schedule")


class PreviewIn(BaseModel):
    cron_expr: str = Field(max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    count: int = Field(default=5, ge=1, le=20)
    start: datetime | None = Field(default=None, description="Preview from this moment (default: now)")


class PreviewRunOut(BaseModel):
    local: datetime
    utc: datetime


class PreviewOut(BaseModel):
    cron_expr: str
    timezone: str
    human: str
    runs: list[PreviewRunOut]
    notes: list[str] = Field(description="Daylight-saving warnings")

    @classmethod
    def of(cls, value: Preview) -> PreviewOut:
        return cls(
            cron_expr=value.expression,
            timezone=value.timezone,
            human=value.description,
            runs=[PreviewRunOut(local=run.local, utc=run.utc) for run in value.runs],
            notes=value.notes,
        )


class SchedulerStatusOut(BaseModel):
    instance_id: str
    running: bool | None = Field(description="None: unknown (the instance has no agnostic-bridge to ask)")
    poll_interval_seconds: float | None
    can_write: bool
    can_delete: bool
    can_custom_endpoint: bool = Field(description="Instance admins may schedule any endpoint")

    @classmethod
    def of(cls, status: SchedulerStatus) -> SchedulerStatusOut:
        return cls(
            instance_id=status.instance.id,
            running=status.enabled,
            poll_interval_seconds=status.poll_interval_seconds,
            can_write=status.can_write,
            can_delete=status.can_delete,
            can_custom_endpoint=status.can_custom,
        )


class EndpointCheckOut(BaseModel):
    target_kind: TargetKindName
    target_id: str | None
    documented: bool | None = Field(description="In the instance's OpenAPI document; None when it publishes none")
    needs_admin: bool

    @classmethod
    def of(cls, check: EndpointCheck) -> EndpointCheckOut:
        return cls(
            target_kind=check.target.kind,
            target_id=check.target.id,
            documented=check.documented,
            needs_admin=check.needs_admin,
        )
