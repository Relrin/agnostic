"""Compare two batches over the same dataset, case by case, and say what changed in one sentence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from agnostic_evals.domain.model import LOW_SCORE, Item, Outcome

type Change = Literal["regression", "fix", "same", "missing"]

BIG_DROP = 2.0
"""A score change this large counts even when both sides stay above the threshold."""


@dataclass(frozen=True, slots=True)
class CaseChange:
    case_id: str
    position: int
    input: str
    expected: str | None
    before: Item | None
    after: Item | None
    change: Change


def _score(item: Item | None) -> Outcome | None:
    return item.outcome if item is not None and item.status == "done" else None


def _by_score(before: float, after: float, threshold: float) -> Change:
    low_before, low_after = before < threshold, after < threshold
    drop = before - after
    if drop > 0 and ((low_after and not low_before) or drop >= BIG_DROP):
        return "regression"
    if drop < 0 and ((low_before and not low_after) or -drop >= BIG_DROP):
        return "fix"
    return "same"


def classify(before: Outcome | None, after: Outcome | None, threshold: float = LOW_SCORE) -> Change:
    if before is None or after is None:
        return "missing"
    if before.score is not None and after.score is not None:
        return _by_score(before.score, after.score, threshold)
    if before.passed is True and after.passed is False:
        return "regression"
    if before.passed is False and after.passed is True:
        return "fix"
    return "same"


def compare_cases(before: Sequence[Item], after: Sequence[Item], threshold: float = LOW_SCORE) -> list[CaseChange]:
    """Items of two batches matched by case, in dataset order (the newer batch's snapshot describes the case)."""
    old = {item.case_id: item for item in before}
    new = {item.case_id: item for item in after}
    rows: list[CaseChange] = []
    for case_id in {**old, **new}:
        a, b = old.get(case_id), new.get(case_id)
        shown = cast("Item", b or a)
        rows.append(
            CaseChange(
                case_id=case_id,
                position=shown.position,
                input=shown.input,
                expected=shown.expected,
                before=a,
                after=b,
                change=classify(_score(a), _score(b), threshold),
            )
        )
    rows.sort(key=lambda row: row.position)
    return rows


@dataclass(frozen=True, slots=True)
class ComparisonCounts:
    regressions: int
    fixes: int
    below_before: int
    below_after: int


def counts(rows: Sequence[CaseChange], threshold: float = LOW_SCORE) -> ComparisonCounts:
    def below(item: Item | None) -> bool:
        outcome = _score(item)
        return outcome is not None and outcome.score is not None and outcome.score < threshold

    return ComparisonCounts(
        regressions=sum(1 for row in rows if row.change == "regression"),
        fixes=sum(1 for row in rows if row.change == "fix"),
        below_before=sum(1 for row in rows if below(row.before)),
        below_after=sum(1 for row in rows if below(row.after)),
    )


def _transition(row: CaseChange) -> str:
    before, after = _score(row.before), _score(row.after)
    if before is not None and after is not None and before.score is not None and after.score is not None:
        return f"{before.score:g} → {after.score:g}"
    return "pass → fail" if row.change == "regression" else "fail → pass"


def _cases(rows: Sequence[CaseChange], *, transitions: bool) -> str:
    noun = "case" if len(rows) == 1 else "cases"
    numbers = [str(row.position) for row in rows]
    listed = numbers[0] if len(numbers) == 1 else ", ".join(numbers[:-1]) + f" and {numbers[-1]}"
    if not transitions:
        return f"{noun} {listed}"
    return f"{noun} {listed} ({', '.join(_transition(row) for row in rows)})"


def insight(rows: Sequence[CaseChange], before_label: str, after_label: str) -> str:
    """Deterministic: which cases the newer version fixes and which it regresses."""
    fixes = [row for row in rows if row.change == "fix"]
    regressions = [row for row in rows if row.change == "regression"]
    if fixes and regressions:
        return (
            f"{after_label} fixes {_cases(fixes, transitions=False)} but regresses "
            f"{_cases(regressions, transitions=True)} compared with {before_label}."
        )
    if regressions:
        return f"{after_label} regresses {_cases(regressions, transitions=True)} compared with {before_label}."
    if fixes:
        return f"{after_label} fixes {_cases(fixes, transitions=True)} with no regressions against {before_label}."
    missing = sum(1 for row in rows if row.change == "missing")
    if missing:
        return f"No scored case changed between {before_label} and {after_label}; {missing} lack a result on one side."
    return f"No case changed between {before_label} and {after_label}."
