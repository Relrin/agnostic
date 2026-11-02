"""Normalise AgentOS eval results (``EvalSchema``) into one outcome per case, and summarise a batch.

``eval_data`` by type (agno ``agno/eval``): accuracy → ``results[{output, score, reason}]`` + ``avg_score``;
agent as judge → ``results[{output, score|None, reason, passed}]`` + ``pass_rate``; reliability → ``eval_status``
(``PASSED``/``FAILED``) + tool-call lists; performance → ``run_times`` (seconds) + ``avg_run_time``.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from agnostic_evals.domain.model import LOW_SCORE, EvalType, Outcome


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _results(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [entry for item in cast("list[Any]", data.get("results") or []) if (entry := _dict(item))]


def _text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def outcome(eval_type: EvalType, body: Mapping[str, Any], threshold: float = LOW_SCORE) -> Outcome:
    data = _dict(body.get("eval_data"))
    results = _results(data)
    first = results[0] if results else {}
    if eval_type == "accuracy":
        scores = [score for item in results if (score := _number(item.get("score"))) is not None]
        score = _number(data.get("avg_score"))
        if score is None and scores:
            score = statistics.mean(scores)
        return Outcome(
            score=score,
            passed=score >= threshold if score is not None else None,
            reason=_text(first.get("reason")),
            actual=_text(first.get("output")),
        )
    if eval_type == "agent_as_judge":
        score = _number(first.get("score")) if len(results) == 1 else _number(data.get("avg_score"))
        passed = first.get("passed") if len(results) == 1 else None
        if passed is None:
            rate = _number(data.get("pass_rate"))
            passed = rate >= 50 if rate is not None else (score >= threshold if score is not None else None)  # noqa: PLR2004
        return Outcome(
            score=score,
            passed=bool(passed) if passed is not None else None,
            reason=_text(first.get("reason")),
            actual=_text(first.get("output")),
        )
    if eval_type == "reliability":
        status = str(data.get("eval_status") or "").upper()
        missing = cast("list[Any]", data.get("missing_tool_calls") or data.get("failed_tool_calls") or [])
        failed_args = cast("list[Any]", data.get("failed_argument_checks") or [])
        problems = [f"missing {', '.join(map(str, missing))}"] if missing else []
        if failed_args:
            problems.append(f"wrong arguments: {', '.join(map(str, failed_args))}")
        called = cast("list[Any]", data.get("passed_tool_calls") or [])
        reason = "; ".join(problems) if problems else (f"Called {', '.join(map(str, called))}." if called else None)
        return Outcome(score=None, passed=status == "PASSED" if status else None, reason=reason, actual=None)
    seconds = _number(data.get("avg_run_time"))
    if seconds is None:
        times = [time for item in cast("list[Any]", data.get("run_times") or []) if (time := _number(item)) is not None]
        seconds = statistics.mean(times) if times else None
    return Outcome(
        score=None,
        passed=None,
        reason=f"{seconds:.2f} s average run time" if seconds is not None else None,
        actual=None,
        latency_ms=seconds * 1000 if seconds is not None else None,
    )


@dataclass(frozen=True, slots=True)
class Summary:
    runs: int
    completed: int
    errors: int
    avg: float | None
    mean: float | None
    min: float | None
    max: float | None
    std_dev: float | None
    passed: int
    failed: int
    avg_latency_ms: float | None
    below_threshold: int

    @property
    def pass_ratio(self) -> float | None:
        judged = self.passed + self.failed
        return self.passed / judged if judged else None

    @property
    def gate_value(self) -> float | None:
        """What a publish gate compares with its minimum: the average score, or the pass ratio scaled to ten."""
        if self.avg is not None:
            return self.avg
        ratio = self.pass_ratio
        return ratio * 10 if ratio is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "completed": self.completed,
            "errors": self.errors,
            "avg": self.avg,
            "mean": self.mean,
            "min": self.min,
            "max": self.max,
            "std_dev": self.std_dev,
            "passed": self.passed,
            "failed": self.failed,
            "avg_latency_ms": self.avg_latency_ms,
            "below_threshold": self.below_threshold,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Summary:
        return cls(
            runs=int(value.get("runs") or 0),
            completed=int(value.get("completed") or 0),
            errors=int(value.get("errors") or 0),
            avg=_number(value.get("avg")),
            mean=_number(value.get("mean")),
            min=_number(value.get("min")),
            max=_number(value.get("max")),
            std_dev=_number(value.get("std_dev")),
            passed=int(value.get("passed") or 0),
            failed=int(value.get("failed") or 0),
            avg_latency_ms=_number(value.get("avg_latency_ms")),
            below_threshold=int(value.get("below_threshold") or 0),
        )


def summarize(runs: int, outcomes: Sequence[Outcome | None], threshold: float = LOW_SCORE) -> Summary:
    """``outcomes`` holds one entry per finished case (``None`` for a case that errored)."""
    done = [item for item in outcomes if item is not None]
    scores = [item.score for item in done if item.score is not None]
    latencies = [item.latency_ms for item in done if item.latency_ms is not None]
    return Summary(
        runs=runs,
        completed=len(done),
        errors=len(outcomes) - len(done),
        avg=round(statistics.mean(scores), 4) if scores else None,
        mean=round(statistics.mean(scores), 4) if scores else None,
        min=min(scores) if scores else None,
        max=max(scores) if scores else None,
        std_dev=round(statistics.stdev(scores), 4) if len(scores) > 1 else (0.0 if scores else None),
        passed=sum(1 for item in done if item.passed is True),
        failed=sum(1 for item in done if item.passed is False),
        avg_latency_ms=statistics.mean(latencies) if latencies else None,
        below_threshold=sum(1 for score in scores if score < threshold),
    )


def headline(eval_type: EvalType, summary: Summary) -> str:
    """The table's Result column: ``9.10 avg``, ``8 / 10 pass``, ``Passed`` / ``Failed 1 of 6``, ``3.2 s avg``."""
    if summary.completed == 0:
        return "No results" if summary.errors else "Pending"
    if eval_type == "performance" and summary.avg_latency_ms is not None:
        return f"{summary.avg_latency_ms / 1000:.1f} s avg"
    if eval_type == "reliability":
        judged = summary.passed + summary.failed
        return "Passed" if summary.failed == 0 else f"Failed {summary.failed} of {judged}"
    if eval_type == "agent_as_judge":
        return f"{summary.passed} / {summary.passed + summary.failed} pass"
    if summary.avg is not None:
        return f"{summary.avg:.2f} avg"
    return f"{summary.passed} / {summary.passed + summary.failed} pass"
