"""AgentOS trace details as flat, depth-annotated spans.

``GET /traces/{trace_id}`` returns a ``TraceNode`` tree (agno ``os/routers/traces/schemas.py``): ``type`` is the
derived span kind (``WORKFLOW`` for chains, ``AGENT``, ``TEAM``, ``LLM``, ``TOOL``, …), times are ISO strings, and the
OpenInference attributes are folded into ``metadata``/``input``/``output``/``error``. This module flattens the tree
in display order (depth first, children by start time), names each span by its path from the root, and rebuilds the
OpenInference attribute keys the trace detail shows.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from agnostic_observe.domain.overview import parse_duration, parse_time

type SpanKind = Literal["workflow", "step", "agent", "team", "model", "tool", "other"]
type ComponentKind = Literal["agent", "team", "workflow"]

_KINDS: Mapping[str, SpanKind] = {
    "WORKFLOW": "workflow",
    "CHAIN": "workflow",
    "STEP": "step",
    "AGENT": "agent",
    "TEAM": "team",
    "LLM": "model",
    "TOOL": "tool",
}
_OPENINFERENCE: Mapping[SpanKind, str] = {
    "workflow": "CHAIN",
    "step": "CHAIN",
    "agent": "AGENT",
    "team": "AGENT",
    "model": "LLM",
    "tool": "TOOL",
    "other": "UNKNOWN",
}
_METADATA_KEYS: Mapping[str, str] = {
    "model": "llm.model_name",
    "input_tokens": "llm.token_count.prompt",
    "output_tokens": "llm.token_count.completion",
    "tool_name": "tool.name",
    "parameters": "tool.parameters",
    "run_id": "agno.run.id",
    "session_id": "session.id",
    "user_id": "user.id",
    "total_input_tokens": "llm.token_count.prompt",
    "total_output_tokens": "llm.token_count.completion",
}
_EARLIEST = datetime.min.replace(tzinfo=UTC)
_VERSION_KEYS = ("component_version", "version", "agno.component.version", "agno.version.number")


@dataclass(frozen=True, slots=True)
class Span:
    id: str
    parent_id: str | None
    name: str
    kind: SpanKind
    depth: int
    path: tuple[str, ...]
    """Names from the root to this span: the key that aligns spans across two runs."""
    start_ms: float
    """Offset from the trace start."""
    duration_ms: float
    status: str
    attributes: Mapping[str, Any] = field(default_factory=dict[str, Any])

    @property
    def failed(self) -> bool:
        return self.status.upper() == "ERROR"

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass(frozen=True, slots=True)
class ModelTokens:
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class TraceView:
    trace_id: str
    name: str
    status: str
    start: datetime | None
    duration_ms: float
    run_id: str | None
    session_id: str | None
    user_id: str | None
    component_kind: ComponentKind | None
    component_id: str | None
    version: int | None
    input: str | None
    output: str | None
    error: str | None
    spans: Sequence[Span]
    models: Sequence[ModelTokens]

    @property
    def failed(self) -> bool:
        return self.status.upper() == "ERROR" or any(span.failed for span in self.spans)

    @property
    def error_count(self) -> int:
        return sum(1 for span in self.spans if span.failed)

    @property
    def input_tokens(self) -> int:
        return sum(model.input_tokens for model in self.models)

    @property
    def output_tokens(self) -> int:
        return sum(model.output_tokens for model in self.models)


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return 0


def _version(*sources: Mapping[str, Any]) -> int | None:
    for source in sources:
        for key in _VERSION_KEYS:
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lstrip("v").isdigit():
                return int(value.lstrip("v"))
    return None


def _kind(node: Mapping[str, Any], depth: int) -> SpanKind:
    kind = _KINDS.get(str(node.get("type") or "").upper(), "other")
    # Workflow steps are chains under the workflow root; agno labels them with step_type.
    if depth > 0 and (node.get("step_type") or kind == "workflow"):
        return "step"
    return kind


def _attributes(node: Mapping[str, Any], kind: SpanKind, duration_ms: float) -> dict[str, Any]:
    attributes: dict[str, Any] = {"openinference.span.kind": _OPENINFERENCE[kind]}
    for key, value in _dict(node.get("metadata")).items():
        attributes[_METADATA_KEYS.get(key, key)] = value
    if kind == "tool" and "tool.name" not in attributes:
        attributes["tool.name"] = node.get("name")
    if node.get("step_type"):
        attributes["agno.step.type"] = node["step_type"]
    attributes["input.value"] = node.get("input")
    attributes["output.value"] = node.get("output")
    attributes["status"] = str(node.get("status") or "OK").upper()
    attributes["duration_ms"] = round(duration_ms)
    if error := node.get("error"):
        text = str(error)
        exc_type, _, message = text.partition(": ")
        if message and exc_type.replace(".", "").isidentifier() and exc_type[:1].isupper():
            attributes["exception.type"] = exc_type
            attributes["exception.message"] = message
        else:
            attributes["exception.message"] = text
    for key, value in _dict(node.get("extra_data")).items():
        attributes.setdefault(key, value)
    return attributes


def _duration(node: Mapping[str, Any], start: datetime | None, end: datetime | None) -> float:
    if start is not None and end is not None:
        return max((end - start).total_seconds() * 1000, 0.0)
    return parse_duration(node.get("duration")) or 0.0


def flatten(tree: Iterable[Mapping[str, Any]], origin: datetime | None) -> list[Span]:
    """Depth-first, children ordered by start time (the waterfall's row order)."""
    spans: list[Span] = []

    def visit(node: Mapping[str, Any], parent: Span | None) -> None:
        start, end = parse_time(node.get("start_time")), parse_time(node.get("end_time"))
        duration = _duration(node, start, end)
        depth = parent.depth + 1 if parent else 0
        kind = _kind(node, depth)
        name = str(node.get("name") or "span")
        offset = (start - origin).total_seconds() * 1000 if start is not None and origin is not None else 0.0
        span = Span(
            id=str(node.get("id") or f"{name}:{len(spans)}"),
            parent_id=parent.id if parent else None,
            name=name,
            kind=kind,
            depth=depth,
            path=(*parent.path, name) if parent else (name,),
            start_ms=max(offset, 0.0),
            duration_ms=duration,
            status=str(node.get("status") or "OK").upper(),
            attributes=_attributes(node, kind, duration),
        )
        spans.append(span)
        children = [child for item in cast("list[Any]", node.get("spans") or []) if (child := _dict(item))]
        children.sort(key=lambda child: parse_time(child.get("start_time")) or _EARLIEST)
        for child in children:
            visit(child, span)

    roots = [_dict(node) for node in tree if isinstance(node, dict)]  # pyright: ignore[reportUnnecessaryIsInstance]
    roots.sort(key=lambda node: parse_time(node.get("start_time")) or _EARLIEST)
    for root in roots:
        visit(root, None)
    return spans


def model_rollup(spans: Iterable[Span]) -> list[ModelTokens]:
    """Model calls in the trace, per model name (most tokens first)."""
    totals: dict[str, list[int]] = {}
    for span in spans:
        if span.kind != "model":
            continue
        model = str(span.attributes.get("llm.model_name") or span.name)
        entry = totals.setdefault(model, [0, 0, 0])
        entry[0] += 1
        entry[1] += _int(span.attributes.get("llm.token_count.prompt"))
        entry[2] += _int(span.attributes.get("llm.token_count.completion"))
    rows = [ModelTokens(model, calls, prompt, completion) for model, (calls, prompt, completion) in totals.items()]
    rows.sort(key=lambda row: (-(row.input_tokens + row.output_tokens), row.model))
    return rows


def parse_trace(raw: Mapping[str, Any]) -> TraceView:
    """A ``TraceDetail`` body (tolerant of missing fields)."""
    start, end = parse_time(raw.get("start_time")), parse_time(raw.get("end_time"))
    tree = [node for item in cast("list[Any]", raw.get("tree") or []) if (node := _dict(item))]
    spans = flatten(tree, start)
    if start is not None and end is not None:
        duration = max((end - start).total_seconds() * 1000, 0.0)
    else:
        duration = parse_duration(raw.get("duration")) or max((span.end_ms for span in spans), default=0.0)
    kind: ComponentKind | None = None
    component: str | None = None
    for key, name in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
        if raw.get(key):
            kind, component = cast("ComponentKind", name), str(raw[key])
            break
    root = tree[0] if tree else {}
    version = _version(raw, _dict(root.get("metadata")), _dict(root.get("extra_data")))
    rollup = model_rollup(spans)
    if not rollup and (metadata := _dict(root.get("metadata"))):
        prompt, completion = _int(metadata.get("total_input_tokens")), _int(metadata.get("total_output_tokens"))
        if prompt or completion:
            rollup = [ModelTokens("unknown", 0, prompt, completion)]
    return TraceView(
        trace_id=str(raw.get("trace_id") or ""),
        name=str(raw.get("name") or (spans[0].name if spans else "")),
        status=str(raw.get("status") or "OK").upper(),
        start=start,
        duration_ms=duration,
        run_id=cast("str | None", raw.get("run_id")),
        session_id=cast("str | None", raw.get("session_id")),
        user_id=cast("str | None", raw.get("user_id")),
        component_kind=kind,
        component_id=component,
        version=version,
        input=cast("str | None", raw.get("input")),
        output=cast("str | None", raw.get("output")),
        error=cast("str | None", raw.get("error")),
        spans=spans,
        models=rollup,
    )


def input_shape(value: str | None) -> str | None:
    """A coarse fingerprint of a run input: the key set of a JSON object, ``list``, ``text``, or ``None``."""
    if value is None or not value.strip():
        return None
    try:
        parsed: object = json.loads(value)
    except ValueError:
        return "text"
    if isinstance(parsed, dict):
        return "keys:" + ",".join(sorted(str(key) for key in cast("dict[str, Any]", parsed)))
    if isinstance(parsed, list):
        return "list"
    return "text"
