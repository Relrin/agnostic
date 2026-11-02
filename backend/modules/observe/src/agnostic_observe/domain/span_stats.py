"""Slowest span types: average duration per span name across a sample of traces."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agnostic_observe.domain.traces import Span, SpanKind


@dataclass(frozen=True, slots=True)
class SpanTypeStat:
    name: str
    kind: SpanKind
    avg_ms: float
    count: int
    errors: int


def span_type_stats(traces: Iterable[Sequence[Span]], limit: int = 10) -> list[SpanTypeStat]:
    """Slowest first. A span name seen with several kinds takes the most frequent one."""
    totals: dict[str, list[float]] = {}
    kinds: dict[str, dict[SpanKind, int]] = {}
    for spans in traces:
        for span in spans:
            entry = totals.setdefault(span.name, [0.0, 0, 0])
            entry[0] += span.duration_ms
            entry[1] += 1
            entry[2] += 1 if span.failed else 0
            seen = kinds.setdefault(span.name, {})
            seen[span.kind] = seen.get(span.kind, 0) + 1
    stats = [
        SpanTypeStat(
            name=name,
            kind=max(kinds[name].items(), key=lambda item: item[1])[0],
            avg_ms=total / count,
            count=int(count),
            errors=int(errors),
        )
        for name, (total, count, errors) in totals.items()
    ]
    stats.sort(key=lambda stat: (-stat.avg_ms, stat.name))
    return stats[:limit]
