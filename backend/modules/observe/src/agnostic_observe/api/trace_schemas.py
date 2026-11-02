"""Response bodies of the trace comparison and span-statistics endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_observe.application.traces import SpanStats, TraceComparison
from agnostic_observe.domain.comparison import SpanGroup

type SpanKindOut = Literal["workflow", "step", "agent", "team", "model", "tool", "other"]


class SpanGroupOut(BaseModel):
    count: int = Field(description="How many times the span ran (×N)")
    total_ms: float
    mean_ms: float
    max_ms: float
    errors: int

    @classmethod
    def of(cls, group: SpanGroup | None) -> SpanGroupOut | None:
        if group is None:
            return None
        return cls(
            count=group.count,
            total_ms=group.total_ms,
            mean_ms=group.mean_ms,
            max_ms=group.max_ms,
            errors=group.errors,
        )


class ComparisonRowOut(BaseModel):
    path: list[str] = Field(description="Span names from the root: the alignment key")
    name: str
    depth: int
    kind: SpanKindOut
    state: Literal["same", "slower", "faster", "new", "not_run", "error"]
    baseline: SpanGroupOut | None
    current: SpanGroupOut | None
    delta_ms: float | None


class GhostOut(BaseModel):
    span_id: str = Field(description="The span of this trace the ghost bar is drawn under")
    start_ms: float
    duration_ms: float


class BaselineOut(BaseModel):
    trace_id: str
    name: str
    start_time: datetime | None
    duration_ms: float
    version: int | None


class TraceComparisonOut(BaseModel):
    trace_id: str
    baseline: BaselineOut | None
    reason: str | None = Field(description="Why there is no baseline")
    same_version: bool | None = None
    same_input_shape: bool | None = None
    current_duration_ms: float | None = None
    rows: list[ComparisonRowOut] = Field(default_factory=list[ComparisonRowOut])
    ghosts: list[GhostOut] = Field(default_factory=list[GhostOut])
    diagnosis: str | None = None
    generated: bool = Field(default=False, description="Always false: the diagnosis comes from fixed templates")
    cached: bool = False

    @classmethod
    def of(cls, result: TraceComparison) -> TraceComparisonOut:
        baseline = result.baseline
        comparison = result.comparison
        if baseline is None or comparison is None:
            return cls(trace_id=result.trace_id, baseline=None, reason=result.reason)
        return cls(
            trace_id=result.trace_id,
            baseline=BaselineOut(
                trace_id=baseline.trace_id,
                name=baseline.name,
                start_time=baseline.start,
                duration_ms=comparison.baseline_duration_ms,
                version=baseline.version,
            ),
            reason=None,
            same_version=comparison.same_version,
            same_input_shape=comparison.same_input_shape,
            current_duration_ms=comparison.current_duration_ms,
            rows=[
                ComparisonRowOut(
                    path=list(row.path),
                    name=row.name,
                    depth=row.depth,
                    kind=row.kind,
                    state=row.state,
                    baseline=SpanGroupOut.of(row.baseline),
                    current=SpanGroupOut.of(row.current),
                    delta_ms=row.delta_ms,
                )
                for row in comparison.rows
            ],
            ghosts=[
                GhostOut(span_id=ghost.span_id, start_ms=ghost.start_ms, duration_ms=ghost.duration_ms)
                for ghost in comparison.ghosts
            ],
            diagnosis=comparison.diagnosis,
            cached=result.cached,
        )


class SpanTypeStatOut(BaseModel):
    name: str
    kind: SpanKindOut
    avg_duration_ms: float
    count: int
    errors: int


class SpanStatsOut(BaseModel):
    window: Literal["24h", "7d", "30d"]
    generated_at: datetime
    traces_scanned: int
    sampled: bool = Field(description="Only the newest traces of the window were scanned")
    cached: bool
    stats: list[SpanTypeStatOut]

    @classmethod
    def of(cls, stats: SpanStats) -> SpanStatsOut:
        return cls(
            window=stats.window,
            generated_at=stats.generated_at,
            traces_scanned=stats.traces_scanned,
            sampled=stats.sampled,
            cached=stats.cached,
            stats=[
                SpanTypeStatOut(
                    name=item.name, kind=item.kind, avg_duration_ms=item.avg_ms, count=item.count, errors=item.errors
                )
                for item in stats.stats
            ],
        )
