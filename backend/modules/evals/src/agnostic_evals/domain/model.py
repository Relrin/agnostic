"""Datasets, cases, batches and their items."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

type EvalType = Literal["accuracy", "agent_as_judge", "reliability", "performance"]
type ComponentKind = Literal["agent", "team"]
type BatchStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
type ItemStatus = Literal["pending", "running", "done", "error", "cancelled"]

EVAL_TYPES: tuple[EvalType, ...] = ("accuracy", "agent_as_judge", "reliability", "performance")
EVAL_TYPE_LABELS: Mapping[EvalType, str] = {
    "accuracy": "Accuracy",
    "agent_as_judge": "Agent as judge",
    "reliability": "Reliability",
    "performance": "Performance",
}
LOW_SCORE = 7.0
"""Scores below this are highlighted, and the default pass threshold of numeric judges."""


class EvalRuleError(ValueError):
    """A request that breaks a rule of the evals domain (shown to the person as it is)."""


@dataclass(frozen=True, slots=True)
class Dataset:
    id: str
    name: str
    description: str
    eval_type: EvalType
    tags: Sequence[str]
    version: int
    case_count: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    dataset_id: str
    position: int
    input: str
    expected_output: str | None = None
    criteria: str | None = None
    expected_tool_calls: Sequence[str] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])

    @property
    def expected(self) -> str | None:
        """What the case table shows under "Expected"."""
        if self.expected_output:
            return self.expected_output
        if self.criteria:
            return self.criteria
        if self.expected_tool_calls:
            return "calls " + ", ".join(self.expected_tool_calls)
        return None


def check_case(eval_type: EvalType, case: Case) -> None:
    """Each eval type needs its own expectation besides the input."""
    if not case.input.strip():
        raise EvalRuleError(f"Case {case.position} has no input.")
    if eval_type == "accuracy" and not (case.expected_output or "").strip():
        raise EvalRuleError(f"Case {case.position} needs an expected output for an accuracy eval.")
    if eval_type == "agent_as_judge" and not (case.criteria or "").strip():
        raise EvalRuleError(f"Case {case.position} needs criteria for an agent-as-judge eval.")
    if eval_type == "reliability" and not case.expected_tool_calls:
        raise EvalRuleError(f"Case {case.position} needs expected tool calls for a reliability eval.")


@dataclass(frozen=True, slots=True)
class Target:
    """The component version a batch evaluates. ``version=None`` is whatever is current when it runs."""

    kind: ComponentKind
    component_id: str
    version: int | None
    draft: bool

    @property
    def label(self) -> str:
        if self.version is None:
            return "current"
        return f"v{self.version} draft" if self.draft else f"v{self.version}"


@dataclass(frozen=True, slots=True)
class Judge:
    model_id: str
    provider: str


@dataclass(frozen=True, slots=True)
class Batch:
    id: str
    instance_id: str
    dataset_id: str
    dataset_name: str
    case_count: int
    name: str
    target: Target
    eval_type: EvalType
    judge: Judge | None
    via_bridge: bool
    params: Mapping[str, Any]
    status: BatchStatus
    progress: float
    started_by: str
    started_by_name: str
    started_at: datetime
    finished_at: datetime | None
    summary: Mapping[str, Any] | None
    error: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}


@dataclass(frozen=True, slots=True)
class Outcome:
    """One case's result, normalised across eval types."""

    score: float | None
    """0–10 for accuracy and numeric judges."""
    passed: bool | None
    reason: str | None
    actual: str | None
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    batch_id: str
    case_id: str
    position: int
    input: str
    """A snapshot of the case when the batch started: later dataset edits don't rewrite results."""
    expected: str | None
    status: ItemStatus
    eval_run_id: str | None
    outcome: Outcome | None
    trace_id: str | None
    error: str | None
