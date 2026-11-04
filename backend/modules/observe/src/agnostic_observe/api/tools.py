"""Assistant tools over traces and metrics. Every AgentOS read is made as the asking person."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_kernel.db import utcnow
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip
from agnostic_observe.application.calls import PersonCalls, page_items
from agnostic_observe.application.metrics import GetMetricsSummary
from agnostic_observe.application.traces import CompareTrace
from agnostic_observe.domain.overview import TraceRow
from agnostic_observe.domain.traces import Span, TraceView, parse_trace

MAX_SPANS = 60
CHANGED_ROWS = 15


class SearchTracesArgs(BaseModel):
    component_id: str | None = Field(None, description="Agent, team or workflow id, e.g. daily-brief")
    component_kind: Literal["agent", "team", "workflow"] | None = Field(None, description="Kind of component_id")
    status: Literal["OK", "ERROR"] | None = None
    run_id: str | None = Field(None, description="The trace of this run (e.g. a schedule run's run_id)")
    since: datetime | None = Field(None, description="Only traces that started after this time (ISO 8601)")
    until: datetime | None = Field(None, description="Only traces that started before this time (ISO 8601)")
    limit: int = Field(10, ge=1, le=25)


class TraceArgs(BaseModel):
    trace_id: str


class MetricsArgs(BaseModel):
    days: int = Field(7, ge=1, le=92, description="Days back from today, inclusive")


def trace_source(call: ToolCall, trace_id: str, name: str | None = None) -> Source:
    label = f"Trace {name} · {trace_id[:8]}" if name else f"Trace {trace_id[:8]}"
    return Source("trace", label, f"/i/{call.instance_slug}/traces/{trace_id}")


def _row(item: dict[str, Any]) -> dict[str, Any]:
    row = TraceRow.parse(item)
    return {
        "trace_id": row.trace_id,
        "name": item.get("name"),
        "status": row.status,
        "start": row.start.isoformat() if row.start else None,
        "duration_ms": round(row.duration_ms) if row.duration_ms is not None else None,
        "errors": row.error_count,
        "component": f"{row.kind}:{row.component_id}" if row.kind else None,
        "run_id": row.run_id,
        "session_id": item.get("session_id"),
    }


async def search_traces(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, SearchTracesArgs)
    calls = await container.get(PersonCalls)
    instance = await calls.instance(call.instance_id)
    params: dict[str, str | int] = {"page": 1, "limit": args.limit}
    if args.component_id:
        params[f"{args.component_kind or 'agent'}_id"] = args.component_id
    if args.status:
        params["status"] = args.status
    if args.run_id:
        params["run_id"] = args.run_id
    if args.since:
        params["start_time"] = args.since.isoformat()
    if args.until:
        params["end_time"] = args.until.isoformat()
    items, total = page_items(await calls.json(call.principal, instance, "/traces", params=params))
    rows = [_row(item) for item in items]
    sources = [trace_source(call, row["trace_id"], row["name"]) for row in rows[:5]]
    return ToolResult({"total": total, "traces": rows}, sources)


def _span(span: Span) -> dict[str, Any]:
    attributes = span.attributes
    value: dict[str, Any] = {
        "path": " › ".join(span.path),
        "kind": span.kind,
        "start_ms": round(span.start_ms),
        "duration_ms": round(span.duration_ms),
        "status": span.status,
    }
    if error := attributes.get("exception.message"):
        value["error"] = clip(f"{attributes.get('exception.type') or 'Error'}: {error}")
    if span.kind == "tool":
        value["tool_args"] = clip(attributes.get("tool.parameters") or attributes.get("input.value"), 300)
    if model := attributes.get("llm.model_name"):
        value["model"] = model
    return value


def _trace(view: TraceView) -> dict[str, Any]:
    return {
        "trace_id": view.trace_id,
        "name": view.name,
        "status": view.status,
        "start": view.start.isoformat() if view.start else None,
        "duration_ms": round(view.duration_ms),
        "component": f"{view.component_kind}:{view.component_id}" if view.component_kind else None,
        "version": view.version,
        "run_id": view.run_id,
        "session_id": view.session_id,
        "user_message": clip(view.input),
        "output": clip(view.output),
        "error": clip(view.error),
        "spans": [_span(span) for span in view.spans[:MAX_SPANS]],
        "spans_omitted": max(0, len(view.spans) - MAX_SPANS),
        "models": [
            {"model": m.model, "calls": m.calls, "input_tokens": m.input_tokens, "output_tokens": m.output_tokens}
            for m in view.models
        ],
    }


async def get_trace(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, TraceArgs)
    calls = await container.get(PersonCalls)
    instance = await calls.instance(call.instance_id)
    view = parse_trace(await calls.json(call.principal, instance, f"/traces/{args.trace_id}"))
    sources = [trace_source(call, view.trace_id, view.name)]
    if view.session_id:
        sources.append(Source("session", "Session", f"/i/{call.instance_slug}/sessions/{view.session_id}"))
    return ToolResult(_trace(view), sources)


async def compare_trace(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, TraceArgs)
    result = await (await container.get(CompareTrace))(call.principal, call.instance_id, args.trace_id)
    sources = [trace_source(call, result.trace_id)]
    if result.baseline is None or result.comparison is None:
        return ToolResult({"trace_id": result.trace_id, "baseline": None, "reason": result.reason}, sources)
    comparison, baseline = result.comparison, result.baseline
    changed = [row for row in comparison.rows if row.state != "same"][:CHANGED_ROWS]
    sources.append(trace_source(call, baseline.trace_id, f"{baseline.name} (last successful)"))
    return ToolResult(
        {
            "trace_id": result.trace_id,
            "baseline": {
                "trace_id": baseline.trace_id,
                "start": baseline.start.isoformat() if baseline.start else None,
                "version": baseline.version,
                "duration_ms": round(baseline.duration_ms),
            },
            "duration_ms": round(comparison.current_duration_ms),
            "same_version": comparison.same_version,
            "same_input_shape": comparison.same_input_shape,
            "diagnosis": comparison.diagnosis,
            "changed_spans": [
                {
                    "path": " › ".join(row.path),
                    "kind": row.kind,
                    "state": row.state,
                    "before_ms": round(row.baseline.total_ms) if row.baseline else None,
                    "after_ms": round(row.current.total_ms) if row.current else None,
                    "errors": row.current.errors if row.current else 0,
                }
                for row in changed
            ],
        },
        sources,
    )


async def get_metrics(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, MetricsArgs)
    last = utcnow().date()
    first = last - timedelta(days=args.days - 1)
    summary = await (await container.get(GetMetricsSummary))(call.principal, call.instance_id, first, last)
    totals = summary.totals
    return ToolResult(
        {
            "from": summary.first.isoformat(),
            "to": summary.last.isoformat(),
            "runs": {"agent": totals.runs.agent, "team": totals.runs.team, "workflow": totals.runs.workflow},
            "sessions": totals.sessions,
            "active_users": totals.active_users,
            "tokens": {"input": totals.tokens.input, "output": totals.tokens.output},
            "estimated_cost": round(summary.cost.total, 2),
            "cost_is_approximate": summary.cost.approximate,
            "models": [
                {"model": m.model.model_id, "runs": m.runs, "share": round(m.share, 3)} for m in summary.model_usage
            ],
            "components": [
                {"id": c.id, "kind": c.kind, "sessions": c.sessions, "runs": c.runs, "tokens": c.tokens.total}
                for c in sorted(summary.components, key=lambda item: -item.tokens.total)[:10]
            ],
            "unavailable": summary.unavailable,
        },
        [Source("metrics", "Metrics", f"/i/{call.instance_slug}/metrics")],
    )


TOOLS = (
    ToolSpec(
        "search_traces",
        "Find recent traces (one per run), newest first, by component, status and time.",
        search_traces,
        SearchTracesArgs,
        "traces:read",
    ),
    ToolSpec(
        "get_trace",
        "One trace with its spans: what ran, how long each step took, errors and the models used.",
        get_trace,
        TraceArgs,
        "traces:read",
    ),
    ToolSpec(
        "compare_trace",
        "Compare a trace with the last successful run of the same component: changed spans and a diagnosis.",
        compare_trace,
        TraceArgs,
        "traces:read",
    ),
    ToolSpec(
        "get_metrics",
        "Usage over the last days: runs, sessions, tokens, estimated cost, models and the busiest components.",
        get_metrics,
        MetricsArgs,
        "metrics:read",
    ),
)
