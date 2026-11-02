"""Compare a trace with the last successful run of the same component.

Spans are aligned by their **name path** from the root (depth-aware, so ``chat.completion`` under two different steps
stay apart). Repeats of a path become one row with a count; occurrence *i* of a path in the current trace gets
occurrence *i* of the baseline as its ghost bar. The diagnosis is a deterministic template chosen by rules (version
and input shape, the most significant leaf change, what never ran, what is new); it is never model-written.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from agnostic_observe.domain.traces import Span, SpanKind, TraceView, input_shape

type RowState = Literal["same", "slower", "faster", "new", "not_run", "error"]

MIN_DELTA_MS = 250.0
"""Smaller differences are noise."""
RELATIVE_DELTA = 0.25
"""…and so are changes under a quarter of the baseline duration."""

_PARENT_WORD: Mapping[SpanKind, str] = {
    "workflow": "the workflow",
    "step": "the step",
    "agent": "the agent",
    "team": "the team",
}


@dataclass(frozen=True, slots=True)
class SpanGroup:
    """All occurrences of one name path in one trace."""

    count: int
    total_ms: float
    max_ms: float
    errors: int
    first_start_ms: float

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    path: tuple[str, ...]
    kind: SpanKind
    baseline: SpanGroup | None
    current: SpanGroup | None
    state: RowState
    leaf: bool

    @property
    def name(self) -> str:
        return self.path[-1]

    @property
    def depth(self) -> int:
        return len(self.path) - 1

    @property
    def delta_ms(self) -> float | None:
        if self.baseline is None or self.current is None:
            return None
        return self.current.total_ms - self.baseline.total_ms


@dataclass(frozen=True, slots=True)
class Ghost:
    """Where the matching baseline span ran, drawn under span ``span_id`` of the current trace."""

    span_id: str
    start_ms: float
    duration_ms: float


@dataclass(frozen=True, slots=True)
class Comparison:
    current_trace_id: str
    baseline_trace_id: str
    current_duration_ms: float
    baseline_duration_ms: float
    same_version: bool | None
    same_input_shape: bool | None
    rows: Sequence[ComparisonRow]
    ghosts: Sequence[Ghost]
    diagnosis: str


def _groups(spans: Iterable[Span]) -> dict[tuple[str, ...], list[Span]]:
    grouped: dict[tuple[str, ...], list[Span]] = defaultdict(list)
    for span in spans:
        grouped[span.path].append(span)
    for occurrences in grouped.values():
        occurrences.sort(key=lambda span: span.start_ms)
    return grouped


def _group(occurrences: Sequence[Span]) -> SpanGroup | None:
    if not occurrences:
        return None
    return SpanGroup(
        count=len(occurrences),
        total_ms=sum(span.duration_ms for span in occurrences),
        max_ms=max(span.duration_ms for span in occurrences),
        errors=sum(1 for span in occurrences if span.failed),
        first_start_ms=occurrences[0].start_ms,
    )


def _significant(delta: float, baseline: SpanGroup) -> bool:
    return abs(delta) >= max(MIN_DELTA_MS, RELATIVE_DELTA * baseline.total_ms)


def _state(baseline: SpanGroup | None, current: SpanGroup | None) -> RowState:
    if current is None:
        return "not_run"
    if baseline is None:
        return "new"
    if current.errors > baseline.errors:
        return "error"
    delta = current.total_ms - baseline.total_ms
    if not _significant(delta, baseline):
        return "same"
    return "slower" if delta > 0 else "faster"


def _order(current: Sequence[Span], baseline: Sequence[Span]) -> list[tuple[str, ...]]:
    """Current display order; baseline-only paths go at the end of their nearest present ancestor's subtree."""
    order: list[tuple[str, ...]] = []
    for span in current:
        if span.path not in order:
            order.append(span.path)
    for span in baseline:
        if span.path in order:
            continue
        index = len(order)
        for size in range(len(span.path) - 1, 0, -1):
            ancestor = span.path[:size]
            subtree = [i for i, path in enumerate(order) if path[:size] == ancestor]
            if subtree:
                index = subtree[-1] + 1
                break
        order.insert(index, span.path)
    return order


def format_ms(ms: float) -> str:
    """``850 ms``, ``4.1 s``, ``30 s``, ``2 min 4 s``."""
    if ms < 1000:  # noqa: PLR2004
        return f"{round(ms)} ms"
    seconds = ms / 1000
    if seconds < 60:  # noqa: PLR2004
        text = f"{seconds:.1f}".removesuffix(".0")
        return f"{text} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s" if rest else f"{minutes} min"


def _timing(group: SpanGroup) -> str:
    return format_ms(group.mean_ms) + (f" ×{group.count}" if group.count > 1 else "")


def _names(rows: Sequence[ComparisonRow]) -> str:
    names = [f"`{row.name}`" for row in rows]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def _topmost(rows: Sequence[ComparisonRow], state: RowState) -> list[ComparisonRow]:
    selected = [row for row in rows if row.state == state]
    paths = {row.path for row in selected}
    return [row for row in selected if not any(row.path[:size] in paths for size in range(1, len(row.path)))]


def _exception(spans: Sequence[Span], path: tuple[str, ...]) -> str | None:
    for span in spans:
        if span.path == path and span.failed:
            value = span.attributes.get("exception.type") or None
            return str(value) if value else None
    return None


def _prefix(current: TraceView, baseline: TraceView, same_version: bool | None, same_shape: bool | None) -> str | None:
    parts: list[str] = []
    if same_version is True:
        parts.append("same version")
    elif same_version is False:
        parts.append(f"different version (v{baseline.version} → v{current.version})")
    if same_shape is True:
        parts.append("same input shape")
    elif same_shape is False:
        parts.append("different input shape")
    if not parts:
        return None
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


def _cause(
    causes: Sequence[ComparisonRow],
    new: Sequence[ComparisonRow],
    not_run: Sequence[ComparisonRow],
    rows: Sequence[ComparisonRow],
    current: TraceView,
) -> list[str]:
    cause = max(causes, key=lambda row: (row.state == "error", abs(row.delta_ms or 0.0)))
    assert cause.baseline is not None
    assert cause.current is not None
    lead = "The only change is" if len(causes) == 1 and not new else "The biggest change is"
    timing = f"{_timing(cause.current)} instead of {_timing(cause.baseline)}"
    if cause.state == "error":
        exc = _exception(current.spans, cause.path)
        failure = f" with {exc}" if exc else ""
        text = f"{lead} `{cause.name}`, which now fails{failure} ({timing})"
    else:
        text = f"{lead} `{cause.name}` latency ({timing})"
    if not_run:
        parent = next((row for row in rows if row.path == not_run[0].path[:-1]), None)
        where = _PARENT_WORD.get(parent.kind, "the run") if parent else "the run"
        text += f", so {where} never reached {_names(not_run)}"
    sentences = [text + "."]
    if len(causes) > 1:
        others = len(causes) - 1
        sentences.append(f"{others} other span{'s' if others > 1 else ''} changed too.")
    return sentences


def diagnose(
    rows: Sequence[ComparisonRow],
    current: TraceView,
    baseline: TraceView,
    *,
    same_version: bool | None,
    same_input_shape: bool | None,
) -> str:
    """One to three plain sentences explaining the difference, built from fixed templates."""
    prefix = _prefix(current, baseline, same_version, same_input_shape)
    sentences = [prefix] if prefix else []
    causes = [row for row in rows if row.leaf and row.state in {"error", "slower", "faster"}]
    not_run = _topmost(rows, "not_run")
    new = [row for row in _topmost(rows, "new") if row.leaf or row.kind != "model"]
    if causes:
        sentences.extend(_cause(causes, new, not_run, rows, current))
    elif not_run:
        sentences.append(f"{_names(not_run)} did not run this time.")
    if new and not causes:
        sentences.append(f"New in this run: {_names(new)}.")
    if not causes and not not_run and not new:
        sentences.append(
            f"No span changed noticeably; the run took {format_ms(current.duration_ms)} "
            f"instead of {format_ms(baseline.duration_ms)}."
        )
    return " ".join(sentences)


def compare(current: TraceView, baseline: TraceView) -> Comparison:
    current_groups, baseline_groups = _groups(current.spans), _groups(baseline.spans)
    order = _order(current.spans, baseline.spans)
    parents = {path[:-1] for path in order if len(path) > 1}
    kinds: dict[tuple[str, ...], SpanKind] = {span.path: span.kind for span in (*baseline.spans, *current.spans)}
    rows: list[ComparisonRow] = []
    for path in order:
        before, after = _group(baseline_groups.get(path, [])), _group(current_groups.get(path, []))
        rows.append(
            ComparisonRow(
                path=path,
                kind=kinds.get(path, "other"),
                baseline=before,
                current=after,
                state=_state(before, after),
                leaf=path not in parents,
            )
        )
    ghosts = [
        Ghost(span.id, match.start_ms, match.duration_ms)
        for path, occurrences in current_groups.items()
        for span, match in zip(occurrences, baseline_groups.get(path, []), strict=False)
    ]
    same_version = (
        current.version == baseline.version if current.version is not None and baseline.version is not None else None
    )
    shapes = input_shape(current.input), input_shape(baseline.input)
    same_shape = shapes[0] == shapes[1] if None not in shapes else None
    return Comparison(
        current_trace_id=current.trace_id,
        baseline_trace_id=baseline.trace_id,
        current_duration_ms=current.duration_ms,
        baseline_duration_ms=baseline.duration_ms,
        same_version=same_version,
        same_input_shape=same_shape,
        rows=rows,
        ghosts=ghosts,
        diagnosis=diagnose(rows, current, baseline, same_version=same_version, same_input_shape=same_shape),
    )
