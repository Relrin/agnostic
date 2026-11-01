"""Response bodies of ``/api/v1/instances/{instance}/overview``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_observe.application.model import Overview
from agnostic_observe.domain.overview import Kpi


class KpiOut(BaseModel):
    value: float | None
    previous: float | None
    delta: float | None
    delta_pct: float | None

    @classmethod
    def of(cls, kpi: Kpi) -> KpiOut:
        return cls(value=kpi.value, previous=kpi.previous, delta=kpi.delta, delta_pct=kpi.delta_pct)


class KpisOut(BaseModel):
    runs: KpiOut | None = None
    sessions: KpiOut | None = None
    error_rate: KpiOut | None = Field(default=None, description="Share of failed runs (0–1), from traces")
    failed_runs: KpiOut | None = None
    p95_latency_ms: KpiOut | None = None


class DayRunsOut(BaseModel):
    date: date
    completed: int
    failed: int


class ModelUsageOut(BaseModel):
    model_id: str
    runs: int
    share: float


class PrimitiveOut(BaseModel):
    id: str
    type: Literal["agent", "team", "workflow"]
    name: str
    live_version: int | None
    draft_version: int | None
    runs: int
    errors: int
    error_rate: float | None
    last_run_at: datetime | None


class ActionOut(BaseModel):
    label: str
    target: str = Field(description="Path inside the instance, e.g. approvals?tool=refund_customer")


class AttentionOut(BaseModel):
    key: str
    kind: Literal["approval_backlog", "error_spike", "schedule_failing", "eval_regression"]
    severity: Literal["warning", "danger"]
    title: str
    detail: str
    action: ActionOut | None


class ActivityActorOut(BaseModel):
    kind: str
    id: str
    display: str


class ActivityOut(BaseModel):
    id: str
    occurred_at: datetime
    actor: ActivityActorOut
    action: str
    summary: str
    resource_display: str | None
    links: dict[str, Any] | None


class CountsOut(BaseModel):
    agents: int = 0
    teams: int = 0
    workflows: int = 0


class OverviewOut(BaseModel):
    instance_id: str
    range: Literal["24h", "7d", "30d"]
    start: datetime
    end: datetime
    generated_at: datetime
    cached: bool
    sampled: bool = Field(description="Trace-derived numbers come from the newest traces only (large instances)")
    counts: CountsOut | None
    kpis: KpisOut | None
    runs_per_day: list[DayRunsOut] | None
    model_usage: list[ModelUsageOut] | None
    primitives: list[PrimitiveOut] | None
    pending_approvals: int | None
    attention: list[AttentionOut]
    activity: list[ActivityOut] | None
    unavailable: dict[str, str] = Field(description="Section → why it is missing (disabled, unreachable, no scope)")

    @classmethod
    def from_domain(cls, overview: Overview) -> OverviewOut:
        return cls(
            instance_id=overview.instance_id,
            range=overview.range,
            start=overview.window.start,
            end=overview.window.end,
            generated_at=overview.generated_at,
            cached=overview.cached,
            sampled=overview.sampled,
            counts=CountsOut(**overview.counts) if overview.counts is not None else None,
            kpis=KpisOut(**{k: KpiOut.of(v) for k, v in overview.kpis.items()}) if overview.kpis is not None else None,
            runs_per_day=[DayRunsOut(date=r.day, completed=r.completed, failed=r.failed) for r in overview.runs_per_day]
            if overview.runs_per_day is not None
            else None,
            model_usage=[ModelUsageOut(model_id=m.model_id, runs=m.runs, share=m.share) for m in overview.model_usage]
            if overview.model_usage is not None
            else None,
            primitives=[
                PrimitiveOut(
                    id=p.id,
                    type=p.kind,
                    name=p.name,
                    live_version=p.live_version,
                    draft_version=p.draft_version,
                    runs=p.runs,
                    errors=p.errors,
                    error_rate=p.error_rate,
                    last_run_at=p.last_run_at,
                )
                for p in overview.primitives
            ]
            if overview.primitives is not None
            else None,
            pending_approvals=overview.approvals.count if overview.approvals is not None else None,
            attention=[
                AttentionOut(
                    key=a.key,
                    kind=a.kind,
                    severity=a.severity,
                    title=a.title,
                    detail=a.detail,
                    action=ActionOut(label=a.action.label, target=a.action.target) if a.action else None,
                )
                for a in overview.attention
            ],
            activity=[
                ActivityOut(
                    id=e.id,
                    occurred_at=e.occurred_at,
                    actor=ActivityActorOut(kind=e.actor.kind, id=e.actor.id, display=e.actor.display),
                    action=e.action,
                    summary=e.summary,
                    resource_display=e.resource_display,
                    links=dict(e.links) if e.links else None,
                )
                for e in overview.activity
            ]
            if overview.activity is not None
            else None,
            unavailable=overview.unavailable,
        )
