"""Approval continuation payloads, attention rules, overview arithmetic, realtime visibility,
palette query parsing, and the in-process event bus."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from agnostic_approvals.domain.decisions import Approval, ApprovalShapeError, args_diff, continue_form
from agnostic_kernel.events import MemoryEventBus, RealtimeEvent
from agnostic_notifications.domain.events import frame, visible
from agnostic_observe.domain.attention import (
    ErrorFacts,
    Facts,
    PendingApprovals,
    ScheduleFacts,
    attention,
    consecutive_failures,
    humanize_age,
)
from agnostic_observe.domain.overview import (
    DayMetrics,
    TraceRow,
    Window,
    metric_rows,
    model_usage,
    parse_duration,
    parse_time,
    percentile,
    primitives,
    runs_per_day,
)
from agnostic_search.domain.query import like_pattern, prefix_tsquery, terms

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def approval(**overrides: object) -> Approval:
    body: dict[str, object] = {
        "id": "apr_1",
        "status": "pending",
        "run_id": "run_1",
        "session_id": "ses_1",
        "user_id": "usr_dana",
        "agent_id": "support-triage",
        "tool_name": "refund_customer",
        "tool_args": {"amount": 49.0, "customer_id": "cus_1"},
        "requirements": [{"tool_execution": {"tool_call_id": "c1", "tool_name": "refund_customer", "tool_args": {}}}],
    }
    body.update(overrides)
    return Approval.parse(body)


# ---------------------------------------------------------------- approvals


def test_args_diff_lists_changed_added_and_removed() -> None:
    assert args_diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == {
        "b": {"before": 2, "after": 3},
        "c": {"before": None, "after": 4},
    }
    assert args_diff({"a": 1}, None) == {}
    assert args_diff({"a": 1}, {}) == {"a": {"before": 1, "after": None}}


def test_agent_continuation_confirms_and_carries_edited_args() -> None:
    family, component, form = continue_form(approval(), "approve", {"amount": 45.0, "customer_id": "cus_1"})
    assert (family, component) == ("agents", "support-triage")
    assert form["session_id"] == "ses_1"
    assert form["user_id"] == "usr_dana"
    assert (form["stream"], form["background"]) == ("false", "true")
    tools = json.loads(form["tools"])
    assert tools == [
        {
            "tool_call_id": "c1",
            "tool_name": "refund_customer",
            "tool_args": {"amount": 45.0, "customer_id": "cus_1"},
            "confirmed": True,
        }
    ]


def test_agent_continuation_without_requirements_falls_back_to_the_approval() -> None:
    _, _, form = continue_form(approval(requirements=[], context={"tool_call_id": "c9"}), "reject", None)
    tools = json.loads(form["tools"])
    assert tools[0]["tool_call_id"] == "c9"
    assert tools[0]["confirmed"] is False
    assert tools[0]["tool_args"] == {"amount": 49.0, "customer_id": "cus_1"}


def test_team_and_workflow_continuations() -> None:
    team = approval(agent_id="billing-agent", team_id="escalation-team")
    family, component, form = continue_form(team, "approve", None)
    assert (family, component) == ("teams", "escalation-team")
    requirements = json.loads(form["requirements"])
    assert requirements[0]["confirmation"] is True
    assert requirements[0]["tool_execution"]["confirmed"] is True

    flow = approval(
        workflow_id="refund-review",
        requirements=[{"step_name": "approve", "requires_confirmation": True, "requires_user_input": True}],
    )
    family, component, form = continue_form(flow, "approve", {"amount": 45.0})
    assert (family, component) == ("workflows", "refund-review")
    steps = json.loads(form["step_requirements"])
    assert steps[0]["confirmed"] is True
    assert steps[0]["user_input"] == {"amount": 45.0}
    _, _, rejected = continue_form(flow, "reject", None)
    assert json.loads(rejected["step_requirements"])[0]["rejected"] is True


def test_approval_shape_errors() -> None:
    with pytest.raises(ApprovalShapeError):
        Approval.parse({"status": "pending"})
    with pytest.raises(ApprovalShapeError):
        _ = approval(agent_id=None).component


# ---------------------------------------------------------------- attention


def test_attention_rules_order_and_copy() -> None:
    facts = Facts(
        now=NOW,
        approvals=PendingApprovals(3, NOW - timedelta(hours=2, minutes=14), "refund_customer", "billing-agent"),
        errors=ErrorFacts(runs=100, failed=8, previous_runs=100, previous_failed=2, latest_failed_trace="tr_9"),
        schedules=(
            ScheduleFacts(
                "sch_1", "daily-brief", 2, "Timeout in `web_search` after 30 s", NOW.replace(hour=3), "run_1"
            ),
            ScheduleFacts("sch_2", "nightly-sync", 0, None, None, None),
        ),
    )
    items = attention(facts)
    assert [item.kind for item in items] == ["error_spike", "schedule_failing", "approval_backlog"]
    backlog = items[-1]
    assert backlog.title == "3 approvals waiting"
    assert backlog.detail == "`refund_customer` on billing-agent · oldest 2h 14m"
    assert items[1].title == "daily-brief failed twice"
    assert items[1].detail == "Timeout in `web_search` after 30 s · 03:00 UTC"
    assert items[0].action is not None
    assert items[0].action.target == "traces/tr_9"


def test_no_attention_for_quiet_instances() -> None:
    quiet = Facts(
        now=NOW,
        approvals=PendingApprovals(0),
        errors=ErrorFacts(runs=100, failed=1, previous_runs=100, previous_failed=1),
    )
    assert attention(quiet) == []
    # Below 5 % and not doubled: no card.
    steady = Facts(now=NOW, errors=ErrorFacts(runs=400, failed=10, previous_runs=400, previous_failed=9))
    assert attention(steady) == []


def test_helpers() -> None:
    assert consecutive_failures(["failed", "error", "success", "failed"]) == 2
    assert consecutive_failures(["success", "failed"]) == 0
    assert humanize_age(timedelta(minutes=5)) == "5m"
    assert humanize_age(timedelta(hours=3)) == "3h"
    assert humanize_age(timedelta(days=4)) == "4d"


# ---------------------------------------------------------------- overview


def test_parsing_mixed_agentos_formats() -> None:
    assert parse_time(1_793_534_400) == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    assert parse_time(1_793_534_400_000) == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    assert parse_time("2026-11-01") == datetime(2026, 11, 1, tzinfo=UTC)
    assert parse_time("not a date") is None
    assert parse_duration("1.5s") == 1500
    assert parse_duration("350ms") == 350
    assert parse_duration("2m 3s") == 123_000
    assert parse_duration("") is None
    assert percentile([5, 1, 3, 2, 4], 0.95) == 5
    assert percentile([], 0.95) is None


def test_runs_per_day_and_model_usage() -> None:
    window = Window(NOW - timedelta(days=2), NOW)
    rows = metric_rows(
        {
            "metrics": [
                {
                    "date": "2026-10-31",
                    "agent_runs_count": 10,
                    "team_runs_count": 2,
                    "model_metrics": [{"model_id": "a", "count": 9}, {"model_id": "b", "count": 3}],
                },
                {"date": "2026-11-01", "agent_runs_count": 5, "model_metrics": [{"model_id": "a", "count": 5}]},
            ]
        }
    )
    assert [row.runs for row in rows] == [12, 5]
    failed = TraceRow.parse(
        {"trace_id": "t", "status": "ERROR", "start_time": "2026-10-31T09:00:00+00:00", "error_count": 1}
    )
    days = runs_per_day(rows, [failed], window)
    assert [(d.day, d.completed, d.failed) for d in days] == [
        (date(2026, 10, 30), 0, 0),
        (date(2026, 10, 31), 11, 1),
        (date(2026, 11, 1), 5, 0),
    ]
    usage = model_usage(rows)
    assert [(m.model_id, m.runs) for m in usage] == [("a", 14), ("b", 3)]
    assert usage[0].share == pytest.approx(14 / 17)
    assert DayMetrics.parse({"agent_runs_count": 1}) is None


def test_primitives_join_config_versions_and_traces() -> None:
    config = {
        "agents": [{"id": "support-triage", "name": "Support triage"}],
        "teams": [{"id": "research-team"}],
        "workflows": [],
    }
    components = [{"component_id": "support-triage", "current_version": 3, "latest_version": 4}]
    traces = [
        TraceRow.parse(
            {"trace_id": "a", "status": "OK", "agent_id": "support-triage", "start_time": "2026-11-01T10:00:00+00:00"}
        ),
        TraceRow.parse(
            {
                "trace_id": "b",
                "status": "ERROR",
                "agent_id": "support-triage",
                "start_time": "2026-11-01T11:00:00+00:00",
            }
        ),
    ]
    found = primitives(config, components, traces)
    assert [(p.id, p.kind, p.live_version, p.draft_version, p.runs, p.errors) for p in found] == [
        ("support-triage", "agent", 3, 4, 2, 1),
        ("research-team", "team", None, None, 0, 0),
    ]
    assert found[0].last_run_at == datetime(2026, 11, 1, 11, 0, tzinfo=UTC)
    assert found[0].error_rate == 0.5


# ---------------------------------------------------------------- realtime and search


def test_visibility_and_frames() -> None:
    grants = {"ins_a": frozenset({"approvals:read"}), "ins_b": frozenset[str]()}
    assert visible("approvals.count", "ins_a", grants)
    assert not visible("approvals.count", "ins_b", grants)
    assert visible("instance.health", "ins_b", grants)
    assert not visible("instance.health", "ins_c", grants)
    assert visible("access.changed", None, grants)
    assert frame("01J", "approvals.count", {"count": 3}) == b'id: 01J\nevent: approvals.count\ndata: {"count":3}\n\n'


def test_palette_query_parsing() -> None:
    assert terms("Support-triage v3!") == ["support", "triage", "v3"]
    assert prefix_tsquery("supp tri") == "supp:* & tri:*"
    assert prefix_tsquery("  !! ") is None
    assert like_pattern("50%_off") == r"%50\%\_off%"


async def test_memory_bus_delivers_and_replays_in_order() -> None:
    clock = [0.0]
    bus = MemoryEventBus(clock=lambda: clock[0])
    subscription = await bus.subscribe(["evt:org"])
    first = RealtimeEvent("access.changed")
    second = RealtimeEvent("approvals.count", {"count": 1}, instance_id="ins_a")
    await bus.publish("evt:org", first)
    await bus.publish("evt:instance:ins_a", second)
    received = await subscription.next(0.1)
    assert received == ("evt:org", first)
    assert await subscription.next(0.01) is None  # not subscribed to the instance channel
    await subscription.close()
    assert bus.subscriber_count == 0

    assert first.id < second.id
    replayed = await bus.replay(["evt:org", "evt:instance:ins_a"], "0")
    assert [event for _, event in replayed] == [first, second]
    assert await bus.replay(["evt:org", "evt:instance:ins_a"], first.id) == [("evt:instance:ins_a", second)]
    clock[0] = 16 * 60  # past the 15-minute replay window
    assert await bus.replay(["evt:org"], "0") == []
    assert RealtimeEvent.from_json(second.to_json()) == second
