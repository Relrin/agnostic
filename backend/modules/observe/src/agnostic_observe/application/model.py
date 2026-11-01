"""The overview aggregate (what the cache holds and the API serialises)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agnostic_audit.facade import AuditEvent
from agnostic_observe.domain.attention import AttentionItem, ErrorFacts, PendingApprovals, ScheduleFacts
from agnostic_observe.domain.overview import DayRuns, Kpi, ModelShare, Primitive, RangeName, TraceRow, Window


class Unavailable(Exception):  # noqa: N818  (a value, not an error that escapes)
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TraceSample:
    rows: list[TraceRow]
    total: int
    failed_total: int
    truncated: bool


@dataclass(slots=True)
class Overview:
    instance_id: str
    range: RangeName
    window: Window
    generated_at: datetime
    counts: dict[str, int] | None = None
    kpis: dict[str, Kpi] | None = None
    runs_per_day: list[DayRuns] | None = None
    model_usage: list[ModelShare] | None = None
    primitives: list[Primitive] | None = None
    approvals: PendingApprovals | None = None
    errors: ErrorFacts | None = None
    schedules: list[ScheduleFacts] | None = None
    attention: list[AttentionItem] = field(default_factory=list[AttentionItem])
    activity: list[AuditEvent] | None = None
    unavailable: dict[str, str] = field(default_factory=dict[str, str])
    sampled: bool = False
    cached: bool = False
