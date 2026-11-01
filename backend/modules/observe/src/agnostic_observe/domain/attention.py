"""The "Needs attention" rules engine.

Rules: pending approvals (backlog > 0), error spikes (error rate ≥ 5 %, or at least double the previous period
with enough runs to mean something), failing schedules (the latest run failed).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

type AttentionKind = Literal["approval_backlog", "error_spike", "schedule_failing", "eval_regression"]
type Severity = Literal["warning", "danger"]

ERROR_RATE_THRESHOLD = 0.05
SPIKE_FACTOR = 2.0
MIN_RUNS_FOR_SPIKE = 20
SEVERITY_ORDER = {"danger": 0, "warning": 1}


@dataclass(frozen=True, slots=True)
class Action:
    label: str
    target: str
    """Path inside the instance (``approvals?tool=refund_customer``) or ``traces/<id>``."""


@dataclass(frozen=True, slots=True)
class AttentionItem:
    key: str
    kind: AttentionKind
    severity: Severity
    title: str
    detail: str
    action: Action | None


@dataclass(frozen=True, slots=True)
class PendingApprovals:
    count: int
    oldest_created_at: datetime | None = None
    top_tool: str | None = None
    top_component: str | None = None


@dataclass(frozen=True, slots=True)
class ErrorFacts:
    runs: int
    failed: int
    previous_runs: int
    previous_failed: int
    worst_component: str | None = None
    latest_failed_trace: str | None = None

    @property
    def rate(self) -> float | None:
        return self.failed / self.runs if self.runs else None

    @property
    def previous_rate(self) -> float | None:
        return self.previous_failed / self.previous_runs if self.previous_runs else None


@dataclass(frozen=True, slots=True)
class ScheduleFacts:
    schedule_id: str
    name: str
    consecutive_failures: int
    last_error: str | None
    last_failed_at: datetime | None
    run_id: str | None


@dataclass(frozen=True, slots=True)
class Facts:
    now: datetime
    approvals: PendingApprovals | None = None
    errors: ErrorFacts | None = None
    schedules: Sequence[ScheduleFacts] = field(default_factory=tuple[ScheduleFacts, ...])


def humanize_age(delta: timedelta) -> str:
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:  # noqa: PLR2004
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{hours // 24}d"


def _approvals(facts: Facts) -> list[AttentionItem]:
    pending = facts.approvals
    if pending is None or pending.count <= 0:
        return []
    noun = "approval" if pending.count == 1 else "approvals"
    parts: list[str] = []
    if pending.top_tool:
        parts.append(f"`{pending.top_tool}`" + (f" on {pending.top_component}" if pending.top_component else ""))
    if pending.oldest_created_at is not None:
        parts.append(f"oldest {humanize_age(facts.now - pending.oldest_created_at)}")
    target = "approvals" + (f"?tool={pending.top_tool}" if pending.top_tool else "")
    return [
        AttentionItem(
            key="approval_backlog",
            kind="approval_backlog",
            severity="warning",
            title=f"{pending.count} {noun} waiting",
            detail=" · ".join(parts) or "Runs are paused until someone decides.",
            action=Action("Review", target),
        )
    ]


def _errors(facts: Facts) -> list[AttentionItem]:
    errors = facts.errors
    if errors is None or errors.rate is None or errors.failed == 0:
        return []
    rate, previous = errors.rate, errors.previous_rate
    spiking = errors.runs >= MIN_RUNS_FOR_SPIKE and previous is not None and rate >= previous * SPIKE_FACTOR
    if rate < ERROR_RATE_THRESHOLD and not spiking:
        return []
    where = f" on {errors.worst_component}" if errors.worst_component else ""
    detail = f"{errors.failed} of {errors.runs} runs failed ({rate:.1%})"
    if previous is not None:
        detail += f", up from {previous:.1%}"
    return [
        AttentionItem(
            key="error_spike",
            kind="error_spike",
            severity="danger",
            title=f"Error rate {rate:.1%}{where}",
            detail=detail,
            action=Action("Open trace", f"traces/{errors.latest_failed_trace}") if errors.latest_failed_trace else None,
        )
    ]


def _schedules(facts: Facts) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for schedule in facts.schedules:
        if schedule.consecutive_failures <= 0:
            continue
        times = {1: "once", 2: "twice"}.get(schedule.consecutive_failures, f"{schedule.consecutive_failures} times")
        parts = [schedule.last_error] if schedule.last_error else []
        if schedule.last_failed_at is not None:
            parts.append(schedule.last_failed_at.strftime("%H:%M UTC"))
        items.append(
            AttentionItem(
                key=f"schedule_failing:{schedule.schedule_id}",
                kind="schedule_failing",
                severity="danger" if schedule.consecutive_failures > 1 else "warning",
                title=f"{schedule.name} failed {times}"
                if schedule.consecutive_failures > 1
                else f"{schedule.name} failed",
                detail=" · ".join(parts) or "The latest scheduled run failed.",
                action=Action("Open trace", f"traces?run_id={schedule.run_id}")
                if schedule.run_id
                else Action("Open schedule", f"schedules/{schedule.schedule_id}"),
            )
        )
    return items


def attention(facts: Facts) -> list[AttentionItem]:
    items = [*_approvals(facts), *_errors(facts), *_schedules(facts)]
    return sorted(items, key=lambda item: SEVERITY_ORDER[item.severity])


def consecutive_failures(statuses: Sequence[str]) -> int:
    """Newest first: how many runs in a row failed before the last success."""
    count = 0
    for status in statuses:
        if status.lower() in {"failed", "error", "timeout", "cancelled"}:
            count += 1
        else:
            break
    return count
