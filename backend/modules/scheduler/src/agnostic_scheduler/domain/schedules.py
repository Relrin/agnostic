"""Schedules as AgentOS stores them, plus what people need to read them: target, run history, failure streaks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

type TargetKind = Literal["agent", "team", "workflow", "custom"]

RUN_ENDPOINT = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs/?$")
FAILED = frozenset({"failed", "error", "timeout"})
KINDS = {"agents": "agent", "teams": "team", "workflows": "workflow"}


def parse_time(value: object) -> datetime | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


@dataclass(frozen=True, slots=True)
class Target:
    kind: TargetKind
    id: str | None


def target_of(method: str, endpoint: str) -> Target:
    """A schedule that POSTs ``/agents/{id}/runs`` targets that agent; anything else is a custom endpoint."""
    match = RUN_ENDPOINT.match(endpoint)
    if method.upper() == "POST" and match:
        return Target(cast("TargetKind", KINDS[match.group(1)]), match.group(2))
    return Target("custom", None)


def run_endpoint(kind: str, component_id: str) -> str:
    family = {"agent": "agents", "team": "teams", "workflow": "workflows"}[kind]
    return f"/{family}/{component_id}/runs"


@dataclass(frozen=True, slots=True)
class ScheduleRun:
    id: str
    schedule_id: str
    attempt: int
    status: str
    status_code: int | None
    run_id: str | None
    session_id: str | None
    error: str | None
    triggered_at: datetime | None
    completed_at: datetime | None
    paused_for_input: bool
    """The run paused for a person (an approval or a confirmation step) before it finished."""

    @classmethod
    def parse(cls, body: Mapping[str, Any]) -> ScheduleRun:
        requirements = body.get("requirements")
        return cls(
            id=str(body.get("id") or ""),
            schedule_id=str(body.get("schedule_id") or ""),
            attempt=int(body.get("attempt") or 1),
            status=str(body.get("status") or "pending").lower(),
            status_code=int(code) if isinstance(code := body.get("status_code"), int) else None,
            run_id=cast("str | None", body.get("run_id")),
            session_id=cast("str | None", body.get("session_id")),
            error=cast("str | None", body.get("error")),
            triggered_at=parse_time(body.get("triggered_at") or body.get("created_at")),
            completed_at=parse_time(body.get("completed_at")),
            paused_for_input=bool(requirements),
        )

    @property
    def failed(self) -> bool:
        return self.status in FAILED

    @property
    def duration_seconds(self) -> float | None:
        if self.triggered_at is None or self.completed_at is None:
            return None
        return max((self.completed_at - self.triggered_at).total_seconds(), 0.0)

    @property
    def states(self) -> list[str]:
        """The badges in run history: ``PAUSED`` then the final state when the run waited for a person."""
        final = self.status.upper()
        return ["PAUSED", final] if self.paused_for_input and final != "PAUSED" else [final]

    def attempt_label(self, max_retries: int) -> str:
        if self.paused_for_input and self.duration_seconds is not None and self.status == "completed":
            return f"paused {round(self.duration_seconds / 60)} min for confirmation"
        if self.paused_for_input and self.status in {"cancelled", "rejected"}:
            return "confirmation not given"
        if self.attempt <= 1:
            return "first attempt"
        return f"retry {self.attempt - 1} of {max_retries}"


def consecutive_failures(runs: Sequence[ScheduleRun]) -> int:
    """Failed runs at the top of the history (newest first) before the last success."""
    count = 0
    for run in runs:
        if run.failed:
            count += 1
        elif run.status in {"completed", "success", "succeeded"}:
            break
    return count
