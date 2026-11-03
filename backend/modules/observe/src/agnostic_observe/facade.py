"""The only import surface other modules may use: how long a workflow's steps take, from its traces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agnostic_kernel.auth import Principal
from agnostic_observe.application.traces import GetSpanStats
from agnostic_observe.domain.overview import RangeName

__all__ = ["RangeName", "StepStat", "StepStats", "StepStatsImpl", "WorkflowStepStats"]


@dataclass(frozen=True, slots=True)
class StepStat:
    name: str
    avg_ms: float
    count: int
    errors: int


@dataclass(frozen=True, slots=True)
class WorkflowStepStats:
    window: RangeName
    traces_scanned: int
    sampled: bool
    steps: list[StepStat]


class StepStats(Protocol):
    async def for_workflow(
        self, principal: Principal, instance_ref: str, workflow_id: str, window: RangeName
    ) -> WorkflowStepStats:
        """Average duration, runs and failures per step name over the workflow's newest traces (needs traces:read)."""
        ...


class StepStatsImpl:
    def __init__(self, span_stats: GetSpanStats) -> None:
        self._span_stats = span_stats

    async def for_workflow(
        self, principal: Principal, instance_ref: str, workflow_id: str, window: RangeName
    ) -> WorkflowStepStats:
        stats = await self._span_stats(principal, instance_ref, window, workflow_id=workflow_id)
        return WorkflowStepStats(
            window=stats.window,
            traces_scanned=stats.traces_scanned,
            sampled=stats.sampled,
            steps=[StepStat(item.name, item.avg_ms, item.count, item.errors) for item in stats.stats],
        )
