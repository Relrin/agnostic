"""Evals domain: scoring per eval type, batch statistics, case comparison and insight, gates, imports, run bodies."""

from datetime import UTC, datetime
from typing import Any

import pytest

from agnostic_evals.domain.compare import classify, compare_cases, counts, insight
from agnostic_evals.domain.gates import Gate, GateResult, consequence
from agnostic_evals.domain.importing import parse_cases, tool_calls
from agnostic_evals.domain.model import Batch, Case, EvalRuleError, Item, Judge, Outcome, Target, check_case
from agnostic_evals.domain.runs import run_input, run_path
from agnostic_evals.domain.scoring import headline, outcome, summarize

NOW = datetime(2026, 11, 2, 9, 12, tzinfo=UTC)


# ---------------------------------------------------------------- scoring


def test_accuracy_outcome_uses_the_average_and_the_first_reason() -> None:
    body = {
        "eval_data": {
            "avg_score": 3,
            "results": [{"output": "billing / normal; called refund_customer", "score": 3, "reason": "Out of window"}],
        }
    }
    result = outcome("accuracy", body)
    assert (result.score, result.passed, result.reason) == (3.0, False, "Out of window")
    assert result.actual == "billing / normal; called refund_customer"


def test_judge_reliability_and_performance_outcomes() -> None:
    judged = outcome("agent_as_judge", {"eval_data": {"results": [{"score": None, "passed": True, "reason": "ok"}]}})
    assert (judged.score, judged.passed) == (None, True)
    failed = outcome(
        "reliability",
        {"eval_data": {"eval_status": "FAILED", "missing_tool_calls": ["refund_customer"], "passed_tool_calls": []}},
    )
    assert (failed.passed, failed.reason) == (False, "missing refund_customer")
    passed = outcome("reliability", {"eval_data": {"eval_status": "PASSED", "passed_tool_calls": ["lookup"]}})
    assert (passed.passed, passed.reason) == (True, "Called lookup.")
    timed = outcome("performance", {"eval_data": {"run_times": [3.0, 3.4]}})
    assert timed.latency_ms == pytest.approx(3200)


def test_summary_statistics_and_headlines() -> None:
    scores = [10, 3, 4, 9, 10]
    summary = summarize(5, [Outcome(score, score >= 7, None, None) for score in scores])
    assert summary.avg == pytest.approx(7.2)
    assert (summary.min, summary.max, summary.below_threshold) == (3, 10, 2)
    assert summary.std_dev == pytest.approx(3.4205, abs=1e-3)
    assert headline("accuracy", summary) == "7.20 avg"
    assert headline("agent_as_judge", summarize(10, [Outcome(None, i < 8, None, None) for i in range(10)])) == (
        "8 / 10 pass"
    )
    reliability = summarize(6, [Outcome(None, i != 0, None, None) for i in range(6)])
    assert headline("reliability", reliability) == "Failed 1 of 6"
    assert reliability.gate_value == pytest.approx(5 / 6 * 10)
    assert headline("performance", summarize(1, [Outcome(None, None, None, None, latency_ms=3200)])) == "3.2 s avg"
    assert headline("accuracy", summarize(2, [None, None])) == "No results"


# ---------------------------------------------------------------- comparison


def item(case: int, score: float | None, *, passed: bool | None = None, batch: str = "b") -> Item:
    return Item(
        id=f"{batch}{case}",
        batch_id=batch,
        case_id=f"c{case}",
        position=case,
        input=f"input {case}",
        expected=None,
        status="done",
        eval_run_id=None,
        outcome=Outcome(score, passed if passed is not None else (score is not None and score >= 7), "why", None),
        trace_id=None,
        error=None,
    )


@pytest.mark.parametrize(
    ("before", "after", "change"),
    [
        (9, 3, "regression"),
        (10, 4, "regression"),
        (6, 10, "fix"),
        (10, 10, "same"),
        (9, 8, "same"),
        (10, 7.5, "regression"),
    ],
)
def test_classify_scores(before: float, after: float, change: str) -> None:
    assert classify(Outcome(before, None, None, None), Outcome(after, None, None, None)) == change


def test_classify_pass_fail_and_missing() -> None:
    assert (
        classify(
            Outcome(None, passed=True, reason=None, actual=None), Outcome(None, passed=False, reason=None, actual=None)
        )
        == "regression"
    )
    assert (
        classify(
            Outcome(None, passed=False, reason=None, actual=None), Outcome(None, passed=True, reason=None, actual=None)
        )
        == "fix"
    )
    assert classify(None, Outcome(None, passed=True, reason=None, actual=None)) == "missing"


def test_v3_to_v4_draft_comparison_and_insight() -> None:
    v3 = [
        item(1, 10, batch="v3"),
        item(2, 9, batch="v3"),
        item(3, 10, batch="v3"),
        item(4, 9, batch="v3"),
        item(5, 6, batch="v3"),
    ]
    v4 = [
        item(1, 10, batch="v4"),
        item(2, 3, batch="v4"),
        item(3, 4, batch="v4"),
        item(4, 9, batch="v4"),
        item(5, 10, batch="v4"),
    ]
    rows = compare_cases(v3, v4)
    assert [row.change for row in rows] == ["same", "regression", "regression", "same", "fix"]
    summary = counts(rows)
    assert (summary.regressions, summary.fixes, summary.below_before, summary.below_after) == (2, 1, 1, 2)
    assert insight(rows, "v3", "v4 draft") == (
        "v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with v3."
    )
    assert insight(compare_cases(v3, v3), "v3", "v3") == "No case changed between v3 and v3."


# ---------------------------------------------------------------- gates


def gate(*, enabled: bool = True, minimum: float = 8.5) -> Gate:
    return Gate("gate_1", "ins_1", "agent", "support-triage", "ds_1", "accuracy", minimum, enabled, None, NOW)


def test_gate_consequences() -> None:
    assert consequence(gate(enabled=False), None).text == "Off: Publish ignores this eval."
    blocked = consequence(gate(), GateResult("evb_1", "v4 draft", 8.4))
    assert (blocked.state, blocked.text) == ("would_block", "v4 draft (8.40) would be blocked from publishing.")
    assert consequence(gate(), GateResult("evb_2", "v3", 9.1)).state == "passes"
    assert consequence(gate(), None).state == "no_result"


# ---------------------------------------------------------------- import and validation


def test_csv_import_with_tool_calls_and_metadata() -> None:
    content = (
        "﻿input,expected_output,expected_tool_calls,team\n"
        '"Charged twice for #4471, refund one","billing / high","refund_customer;lookup",billing\n'
    )
    drafts = parse_cases(content, "csv", "reliability")
    assert drafts[0].input == "Charged twice for #4471, refund one"
    assert drafts[0].expected_tool_calls == ("refund_customer", "lookup")
    assert drafts[0].metadata == {"team": "billing"}


def test_jsonl_import_reports_the_line() -> None:
    content = '{"input": "a", "expected_output": "b"}\n\n{"input": "c"}\n'
    with pytest.raises(EvalRuleError, match="Line 3: Case 2 needs an expected output"):
        parse_cases(content, "jsonl", "accuracy")
    with pytest.raises(EvalRuleError, match="Line 1 is not JSON"):
        parse_cases("nope", "jsonl", "performance")
    with pytest.raises(EvalRuleError, match="input column"):
        parse_cases("question\nx\n", "csv", "performance")


def test_tool_calls_and_case_rules() -> None:
    assert tool_calls('["a", " b "]') == ("a", "b")
    assert tool_calls("a, b") == ("a", "b")
    assert tool_calls("") is None
    with pytest.raises(EvalRuleError, match="criteria"):
        check_case("agent_as_judge", Case("c", "d", 1, "input"))
    check_case("performance", Case("c", "d", 1, "input"))


# ---------------------------------------------------------------- run bodies


def batch(*, bridge: bool, version: int | None = None, judge: Judge | None = None) -> Batch:
    return Batch(
        id="evb_1",
        instance_id="ins_1",
        dataset_id="ds_1",
        dataset_name="billing-tickets-v2",
        case_count=1,
        name="support-triage accuracy",
        target=Target("agent", "support-triage", version, draft=version is not None),
        eval_type="accuracy",
        judge=judge,
        via_bridge=bridge,
        params={"num_iterations": 2},
        status="queued",
        progress=0,
        started_by="usr_1",
        started_by_name="Priya Nair",
        started_at=NOW,
        finished_at=None,
        summary=None,
    )


def test_run_input_through_agentos_and_the_bridge() -> None:
    case = Case("c1", "ds_1", 2, "Refund for last year's plan?", expected_output="explain the policy")
    direct = run_input(batch(bridge=False, judge=None), case)
    assert direct == {
        "eval_type": "accuracy",
        "input": "Refund for last year's plan?",
        "name": "support-triage accuracy · case 2",
        "expected_output": "explain the policy",
        "num_iterations": 2,
        "agent_id": "support-triage",
    }
    assert run_path(batch(bridge=False)) == "/eval-runs"
    pinned: dict[str, Any] = run_input(batch(bridge=True, version=4, judge=Judge("claude-opus-5-5", "anthropic")), case)
    assert (pinned["component_type"], pinned["component_id"], pinned["version"]) == ("agent", "support-triage", 4)
    assert (pinned["model_id"], pinned["model_provider"]) == ("claude-opus-5-5", "anthropic")
    assert "agent_id" not in pinned
    assert run_path(batch(bridge=True)) == "/agnostic/v1/evals/run"
    assert batch(bridge=True, version=4).target.label == "v4 draft"
