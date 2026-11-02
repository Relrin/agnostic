"""Trace parsing and comparison (golden cases), span statistics, cost math and metrics normalisation."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from agnostic_observe.domain.comparison import compare, format_ms
from agnostic_observe.domain.costs import ModelKey, Price, Tokens, cost, estimate, find_price, merged_prices
from agnostic_observe.domain.metrics import (
    ComponentUsage,
    ModelRuns,
    RunsByKind,
    SessionUsage,
    components,
    day_rows,
    model_usage,
    summary_cost,
    totals,
)
from agnostic_observe.domain.overview import TraceRow
from agnostic_observe.domain.span_stats import span_type_stats
from agnostic_observe.domain.traces import input_shape, parse_trace

T0 = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)


def node(
    name: str, kind: str, start: float, seconds: float, status: str = "OK", *children: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    begin = T0 + timedelta(seconds=start)
    return {
        "id": f"{name}@{start}",
        "name": name,
        "type": kind,
        "start_time": begin.isoformat(),
        "end_time": (begin + timedelta(seconds=seconds)).isoformat(),
        "status": status,
        "spans": list(children),
        **extra,
    }


def trace(
    trace_id: str, root: dict[str, Any], *, version: int | None = 3, text: str = '{"topic": "agents"}'
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "trace_id": trace_id,
        "name": root["name"],
        "status": root["status"],
        "start_time": root["start_time"],
        "end_time": root["end_time"],
        "workflow_id": "daily-brief",
        "input": text,
        "tree": [root],
    }
    if version is not None:
        body["component_version"] = version
    return body


def daily_brief_today() -> dict[str, Any]:
    return trace(
        "tr_9c1e7d40",
        node(
            "daily-brief.run",
            "WORKFLOW",
            0,
            64.0,
            "ERROR",
            node(
                "Gather news",
                "WORKFLOW",
                0.1,
                63.8,
                "ERROR",
                node(
                    "news-scout.run",
                    "AGENT",
                    0.1,
                    63.7,
                    "ERROR",
                    node(
                        "chat.completion",
                        "LLM",
                        0.2,
                        1.4,
                        metadata={"model": "claude-haiku-5-5", "input_tokens": 10516, "output_tokens": 1888},
                    ),
                    node(
                        "web_search",
                        "TOOL",
                        1.7,
                        30.0,
                        "ERROR",
                        error="TimeoutError: web_search exceeded the 30 s tool timeout",
                        input='{"query": "agent platform news"}',
                    ),
                    node("chat.completion", "LLM", 31.8, 1.2),
                    node("web_search", "TOOL", 33.1, 30.0, "ERROR", error="TimeoutError: again"),
                ),
                step_type="Step",
            ),
        ),
    )


def daily_brief_yesterday(**kwargs: Any) -> dict[str, Any]:
    return trace(
        "tr_51ab0e93",
        node(
            "daily-brief.run",
            "WORKFLOW",
            0,
            22.8,
            "OK",
            node(
                "Gather news",
                "WORKFLOW",
                0.1,
                7.0,
                "OK",
                node(
                    "news-scout.run",
                    "AGENT",
                    0.1,
                    6.9,
                    "OK",
                    node("chat.completion", "LLM", 0.2, 1.3),
                    node("web_search", "TOOL", 1.6, 4.1),
                    node("chat.completion", "LLM", 5.8, 1.2),
                ),
                step_type="Step",
            ),
            node("Write brief", "WORKFLOW", 7.2, 15.6, "OK", node("writer.run", "AGENT", 7.3, 15.4), step_type="Step"),
        ),
        **kwargs,
    )


# ---------------------------------------------------------------- parsing


def test_parse_flattens_depth_first_with_kinds_paths_and_attributes() -> None:
    view = parse_trace(daily_brief_today())
    assert [(span.name, span.kind, span.depth) for span in view.spans] == [
        ("daily-brief.run", "workflow", 0),
        ("Gather news", "step", 1),
        ("news-scout.run", "agent", 2),
        ("chat.completion", "model", 3),
        ("web_search", "tool", 3),
        ("chat.completion", "model", 3),
        ("web_search", "tool", 3),
    ]
    search = view.spans[4]
    assert search.path == ("daily-brief.run", "Gather news", "news-scout.run", "web_search")
    assert search.start_ms == pytest.approx(1700)
    assert search.duration_ms == pytest.approx(30000)
    assert search.attributes["openinference.span.kind"] == "TOOL"
    assert search.attributes["tool.name"] == "web_search"
    assert search.attributes["exception.type"] == "TimeoutError"
    assert search.attributes["exception.message"] == "web_search exceeded the 30 s tool timeout"
    assert view.duration_ms == pytest.approx(64000)
    assert view.error_count == 5  # the root, the step, the agent and both searches
    assert (view.component_kind, view.component_id, view.version) == ("workflow", "daily-brief", 3)
    top = view.models[0]
    assert (top.model, top.input_tokens, top.output_tokens) == ("claude-haiku-5-5", 10516, 1888)


def test_input_shape() -> None:
    assert input_shape('{"b": 1, "a": 2}') == "keys:a,b"
    assert input_shape("[1, 2]") == "list"
    assert input_shape("Charged twice for #4471") == "text"
    assert input_shape(None) is None


@pytest.mark.parametrize(
    ("ms", "text"), [(850, "850 ms"), (4100, "4.1 s"), (30000, "30 s"), (64000, "1 min 4 s"), (120000, "2 min")]
)
def test_format_ms(ms: float, text: str) -> None:
    assert format_ms(ms) == text


# ---------------------------------------------------------------- comparison goldens


def test_golden_timeout_stops_the_workflow_before_a_step() -> None:
    result = compare(parse_trace(daily_brief_today()), parse_trace(daily_brief_yesterday()))
    rows = {row.name: row for row in result.rows}
    assert rows["web_search"].state == "error"
    assert rows["web_search"].current is not None
    assert rows["web_search"].current.count == 2
    assert rows["chat.completion"].state == "same"
    assert rows["Write brief"].state == "not_run"
    assert rows["writer.run"].state == "not_run"
    assert [row.name for row in result.rows][-2:] == ["Write brief", "writer.run"]
    assert result.same_version is True
    assert result.same_input_shape is True
    assert result.diagnosis == (
        "Same version, same input shape. The only change is `web_search`, which now fails with TimeoutError "
        "(30 s ×2 instead of 4.1 s), so the workflow never reached `Write brief`."
    )
    # Occurrence i of a path is drawn over occurrence i of the baseline; the second web_search has no ghost.
    ghosts = {ghost.span_id: ghost for ghost in result.ghosts}
    assert ghosts["web_search@1.7"].start_ms == pytest.approx(1600)
    assert ghosts["web_search@1.7"].duration_ms == pytest.approx(4100)
    assert "web_search@33.1" not in ghosts
    assert ghosts["chat.completion@31.8"].start_ms == pytest.approx(5800)


def test_golden_repeated_spans_count_and_slow_down() -> None:
    def run(trace_id: str, *calls: float) -> dict[str, Any]:
        tools = [node("zendesk_search", "TOOL", 0.5 + index, seconds) for index, seconds in enumerate(calls)]
        return trace(trace_id, node("support-triage.run", "AGENT", 0, 10, "OK", *tools), version=None, text="hi")

    result = compare(parse_trace(run("now", 0.6, 0.6, 0.6)), parse_trace(run("then", 0.6)))
    row = next(row for row in result.rows if row.name == "zendesk_search")
    assert (row.baseline.count if row.baseline else 0, row.current.count if row.current else 0) == (1, 3)
    assert row.state == "slower"
    assert result.same_version is None
    assert result.diagnosis.startswith("Same input shape. The only change is `zendesk_search` latency (600 ms ×3")


def test_golden_nested_workflows_keep_same_names_apart() -> None:
    def run(trace_id: str, review_seconds: float) -> dict[str, Any]:
        return trace(
            trace_id,
            node(
                "ticket-router.run",
                "WORKFLOW",
                0,
                10,
                "OK",
                node("Triage", "WORKFLOW", 0, 2, "OK", node("chat.completion", "LLM", 0.1, 1.0), step_type="Step"),
                node(
                    "Review",
                    "WORKFLOW",
                    2,
                    review_seconds,
                    "OK",
                    node("chat.completion", "LLM", 2.1, review_seconds - 0.2),
                    step_type="Step",
                ),
            ),
        )

    result = compare(parse_trace(run("now", 7.0)), parse_trace(run("then", 2.0)))
    completions = [row for row in result.rows if row.name == "chat.completion"]
    assert [(row.path[1], row.state) for row in completions] == [("Triage", "same"), ("Review", "slower")]
    assert "`chat.completion` latency (6.8 s instead of 1.8 s)" in result.diagnosis


def test_golden_new_span_and_nothing_else() -> None:
    base = trace("then", node("kb.run", "AGENT", 0, 2, "OK", node("chat.completion", "LLM", 0.1, 1.0)))
    now = trace(
        "now",
        node(
            "kb.run",
            "AGENT",
            0,
            2,
            "OK",
            node("chat.completion", "LLM", 0.1, 1.0),
            node("cache_lookup", "TOOL", 1.2, 0.1),
        ),
    )
    result = compare(parse_trace(now), parse_trace(base))
    assert result.diagnosis == "Same version, same input shape. New in this run: `cache_lookup`."


def test_golden_identical_runs_and_version_change() -> None:
    base = trace("then", node("kb.run", "AGENT", 0, 2.0, "OK", node("chat.completion", "LLM", 0.1, 1.0)), version=7)
    now = trace("now", node("kb.run", "AGENT", 0, 2.1, "OK", node("chat.completion", "LLM", 0.1, 1.05)), version=8)
    result = compare(parse_trace(now), parse_trace(base))
    assert result.same_version is False
    assert result.diagnosis == (
        "Different version (v7 → v8), same input shape. No span changed noticeably; the run took 2.1 s instead of 2 s."
    )


def test_span_type_stats_are_slowest_first() -> None:
    views = [parse_trace(daily_brief_today()), parse_trace(daily_brief_yesterday())]
    stats = span_type_stats((view.spans for view in views), limit=3)
    assert [stat.name for stat in stats] == ["daily-brief.run", "Gather news", "news-scout.run"]
    search = next(stat for stat in span_type_stats(view.spans for view in views) if stat.name == "web_search")
    assert (search.count, search.errors, search.kind) == (3, 2, "tool")
    assert search.avg_ms == pytest.approx((30000 + 30000 + 4100) / 3)


# ---------------------------------------------------------------- cost math

OPUS = Price("claude-opus-5-5", "anthropic", 5, 25)
HAIKU = Price("claude-haiku-5-5", None, 1, 5, cache_read_per_1m=0.1, reasoning_per_1m=8)


def test_cost_bills_cache_reads_and_reasoning_at_their_rates() -> None:
    tokens = Tokens(input=1_000_000, output=200_000, cache_read=400_000, reasoning=50_000)
    # opus has no special rates: cache reads at input, reasoning at output.
    assert cost(tokens, OPUS) == pytest.approx(5 + 200_000 * 25 / 1e6)
    expected = (600_000 * 1 + 400_000 * 0.1 + 150_000 * 5 + 50_000 * 8) / 1e6
    assert cost(tokens, HAIKU) == pytest.approx(expected)


def test_find_price_prefers_the_provider_row_and_estimate_skips_unpriced() -> None:
    prices = [Price("gpt-6.1-sol", None, 2.5, 10), Price("gpt-6.1-sol", "openai", 2, 8), OPUS]
    assert find_price("GPT-6.1-SOL", "openai", prices) == prices[1]
    assert find_price("gpt-6.1-sol", "azure", prices) == prices[0]
    assert find_price("unknown", None, prices) is None
    result = estimate(
        {ModelKey("claude-opus-5-5", "anthropic"): Tokens(1_000_000, 0), ModelKey("mystery"): Tokens(10, 10)}, prices
    )
    assert result.total == pytest.approx(5)
    assert result.unpriced == [ModelKey("mystery")]


def test_instance_prices_override_org_rows() -> None:
    merged = merged_prices([OPUS, HAIKU], [Price("claude-opus-5-5", "anthropic", 4, 20)])
    assert [(price.model_id, price.input_per_1m) for price in merged] == [
        ("claude-haiku-5-5", 1),
        ("claude-opus-5-5", 4),
    ]


# ---------------------------------------------------------------- metrics


def metric_day(day: date, agent: int, model_counts: dict[str, int], tokens: int) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "agent_runs_count": agent,
        "team_runs_count": 1,
        "workflow_runs_count": 2,
        "agent_sessions_count": 3,
        "users_count": 2,
        "token_metrics": {"input_tokens": tokens, "output_tokens": tokens // 4, "cache_read_tokens": tokens // 10},
        "model_metrics": [{"model_id": m, "model_provider": "anthropic", "count": c} for m, c in model_counts.items()],
    }


def test_day_rows_fill_gaps_and_sum_duplicates() -> None:
    first = date(2026, 10, 25)
    rows = day_rows(
        {"metrics": [metric_day(first, 5, {"opus": 5}, 100), metric_day(first, 1, {"opus": 1}, 10)]},
        first,
        first + timedelta(days=2),
    )
    assert [row.runs.agent for row in rows] == [6, 0, 0]
    assert rows[0].runs == RunsByKind(6, 2, 4)
    assert rows[0].tokens == Tokens(input=110, output=27, cache_read=11)
    usage = model_usage(rows)
    assert [(item.model.model_id, item.runs, item.share) for item in usage] == [("opus", 6, 1.0)]


def session(
    session_id: str, component: str, user: str, details: dict[str, tuple[int, int]], extra_input: int = 0
) -> SessionUsage:
    entries = [
        {"id": model, "provider": "anthropic", "input_tokens": i, "output_tokens": o}
        for model, (i, o) in details.items()
    ]
    total_in = sum(i for i, _ in details.values()) + extra_input
    total_out = sum(o for _, o in details.values())
    return SessionUsage.parse(
        {
            "session_id": session_id,
            "agent_id": component,
            "user_id": user,
            "updated_at": "2026-10-30T10:00:00Z",
            "metrics": {"input_tokens": total_in, "output_tokens": total_out, "details": {"model": entries}},
        }
    )


def test_components_from_sessions_with_runs_from_traces() -> None:
    sessions = [
        session("s1", "support-triage", "u1", {"claude-opus-5-5": (1000, 100)}),
        session("s2", "support-triage", "u2", {"claude-opus-5-5": (500, 50)}),
        session(
            "s3", "ticket-router", "u1", {"claude-haiku-5-5": (800, 80), "gpt-6.1-sol": (200, 20)}, extra_input=300
        ),
    ]
    traces = [TraceRow("t1", "OK", None, None, 0, "agent", "support-triage", None)] * 4
    items = {item.id: item for item in components(sessions, traces)}
    triage, router = items["support-triage"], items["ticket-router"]
    assert (triage.sessions, triage.runs, triage.tokens.input, triage.approximate) == (2, 4, 1500, False)
    assert triage.primary_model == ModelKey("claude-opus-5-5", "anthropic")
    assert (router.runs, router.extra_models, router.unattributed.input, router.approximate) == (0, 1, 300, True)
    assert totals([], sessions).active_users == 2


def test_summary_cost_prices_components_and_the_gap() -> None:
    router = ComponentUsage(
        id="ticket-router",
        kind="workflow",
        sessions=1,
        runs=3,
        tokens=Tokens(1300, 100),
        by_model={ModelKey("claude-haiku-5-5"): Tokens(1_000_000, 0), ModelKey("gpt"): Tokens(0, 100)},
        unattributed=Tokens(1_000_000, 0),
    )
    shares = [ModelRuns(ModelKey("claude-haiku-5-5"), 3, 0.75), ModelRuns(ModelKey("gpt"), 1, 0.25)]
    prices = [Price("claude-haiku-5-5", None, 1, 5), Price("gpt", None, 2, 10)]
    result = summary_cost([router], Tokens(4_000_000, 0), shares, prices)
    # 1 M haiku + 100 gpt output tokens + 1 M unattributed at the primary (haiku) rate.
    assert result.components[0].amount == pytest.approx(1 + 100 * 10 / 1e6 + 1)
    assert result.components[0].approximate is True
    assert result.gap == pytest.approx(3 * 1 + 1 * 2)  # 4 M input split 75/25
    assert result.approximate is True
    assert result.total == pytest.approx(result.components[0].amount + result.gap)
    assert result.unpriced == []
