"""Home overview arithmetic: ranges, KPI deltas, runs per day, model usage, latency percentiles. Pure Python.

Sources are AgentOS payloads (daily ``/metrics`` rows, ``/traces`` summaries, ``/config``); everything here is
tolerant of missing fields because the runtime's shapes vary across agno minors.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

type RangeName = Literal["24h", "7d", "30d"]
type Kind = Literal["agent", "team", "workflow"]

RANGES: Mapping[RangeName, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@dataclass(frozen=True, slots=True)
class Window:
    start: datetime
    end: datetime

    @classmethod
    def of(cls, name: RangeName, now: datetime) -> Window:
        return cls(now - RANGES[name], now)

    @property
    def previous(self) -> Window:
        length = self.end - self.start
        return Window(self.start - length, self.start)

    def days(self) -> list[date]:
        first, last = self.start.astimezone(UTC).date(), self.end.astimezone(UTC).date()
        return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True, slots=True)
class Kpi:
    value: float | None
    previous: float | None

    @property
    def delta(self) -> float | None:
        if self.value is None or self.previous is None:
            return None
        return self.value - self.previous

    @property
    def delta_pct(self) -> float | None:
        if self.value is None or not self.previous:
            return None
        return (self.value - self.previous) / self.previous * 100


@dataclass(frozen=True, slots=True)
class TraceRow:
    """The parts of a ``TraceSummary`` the overview uses."""

    trace_id: str
    status: str
    start: datetime | None
    duration_ms: float | None
    error_count: int
    kind: Kind | None
    component_id: str | None
    run_id: str | None

    @property
    def failed(self) -> bool:
        return self.status.upper() == "ERROR" or self.error_count > 0

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> TraceRow:
        start, end = parse_time(raw.get("start_time")), parse_time(raw.get("end_time"))
        duration = (end - start).total_seconds() * 1000 if start and end else parse_duration(raw.get("duration"))
        kind: Kind | None = None
        component: str | None = None
        for key, name in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
            if raw.get(key):
                kind, component = cast("Kind", name), str(raw[key])
                break
        return cls(
            trace_id=str(raw.get("trace_id") or ""),
            status=str(raw.get("status") or "OK"),
            start=start,
            duration_ms=duration,
            error_count=int(raw.get("error_count") or 0),
            kind=kind,
            component_id=component,
            run_id=cast("str | None", raw.get("run_id")),
        )


def parse_time(value: object) -> datetime | None:
    """ISO strings, epoch seconds or milliseconds, or ``YYYY-MM-DD`` (AgentOS mixes all of them)."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_duration(value: object) -> float | None:
    """``"1.2s"``, ``"350ms"``, ``"2m 3s"`` → milliseconds."""
    if not isinstance(value, str) or not value:
        return None
    total = 0.0
    found = False
    for token in value.replace(",", " ").split():
        number = token.rstrip("msh")
        unit = token[len(number) :]
        try:
            amount = float(number)
        except ValueError:
            continue
        factor = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}.get(unit or "s")
        if factor is None:
            continue
        total += amount * factor
        found = True
    return total if found else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; ``None`` for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


# ---------------------------------------------------------------- /metrics rows


@dataclass(frozen=True, slots=True)
class DayMetrics:
    day: date
    runs: int
    sessions: int
    models: Mapping[str, int] = field(default_factory=dict[str, int])

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> DayMetrics | None:
        moment = parse_time(raw.get("date"))
        if moment is None:
            return None
        runs = sum(int(raw.get(f"{kind}_runs_count") or 0) for kind in ("agent", "team", "workflow"))
        sessions = sum(int(raw.get(f"{kind}_sessions_count") or 0) for kind in ("agent", "team", "workflow"))
        models: Counter[str] = Counter()
        for item in cast("list[Any]", raw.get("model_metrics") or []):
            if isinstance(item, dict):
                entry = cast("dict[str, Any]", item)
                model = str(entry.get("model_id") or entry.get("model") or "unknown")
                models[model] += int(entry.get("count") or entry.get("runs") or 0)
        return cls(moment.date(), runs, sessions, dict(models))


def metric_rows(payload: object) -> list[DayMetrics]:
    raw = cast("Mapping[str, Any]", payload).get("metrics") if isinstance(payload, dict) else payload
    rows = [
        DayMetrics.parse(cast("Mapping[str, Any]", item))
        for item in cast("list[Any]", raw or [])
        if isinstance(item, dict)
    ]
    return [row for row in rows if row is not None]


def in_window(rows: Iterable[DayMetrics], window: Window) -> list[DayMetrics]:
    days = set(window.days())
    return [row for row in rows if row.day in days]


@dataclass(frozen=True, slots=True)
class DayRuns:
    day: date
    completed: int
    failed: int


def runs_per_day(rows: Sequence[DayMetrics], traces: Sequence[TraceRow], window: Window) -> list[DayRuns]:
    """Completed = runs counted by ``/metrics`` minus failures seen in traces (traces alone when metrics are empty)."""
    metric_runs = {row.day: row.runs for row in rows}
    traced: dict[date, list[TraceRow]] = defaultdict(list)
    for trace in traces:
        if trace.start is not None:
            traced[trace.start.astimezone(UTC).date()].append(trace)
    result: list[DayRuns] = []
    for day in window.days():
        failed = sum(1 for trace in traced.get(day, ()) if trace.failed)
        total = metric_runs.get(day, len(traced.get(day, ())))
        result.append(DayRuns(day, max(total - failed, 0), failed))
    return result


@dataclass(frozen=True, slots=True)
class ModelShare:
    model_id: str
    runs: int
    share: float


def model_usage(rows: Sequence[DayMetrics]) -> list[ModelShare]:
    totals: Counter[str] = Counter()
    for row in rows:
        totals.update(row.models)
    overall = sum(totals.values())
    return [
        ModelShare(model, count, count / overall if overall else 0.0) for model, count in totals.most_common() if count
    ]


# ---------------------------------------------------------------- primitives


@dataclass(frozen=True, slots=True)
class Primitive:
    id: str
    kind: Kind
    name: str
    live_version: int | None
    draft_version: int | None
    runs: int
    errors: int
    last_run_at: datetime | None

    @property
    def error_rate(self) -> float | None:
        return self.errors / self.runs if self.runs else None


def primitives(
    config: Mapping[str, Any], components: Sequence[Mapping[str, Any]], traces: Sequence[TraceRow]
) -> list[Primitive]:
    """Components from ``/config`` (plus versions from ``/components``) with run counts from the trace sample."""
    versions: dict[str, tuple[int | None, int | None]] = {}
    for item in components:
        component_id = str(item.get("component_id") or item.get("id") or "")
        current = _int(item.get("current_version"))
        latest = _int(item.get("latest_version") or item.get("draft_version"))
        versions[component_id] = (current, latest if latest is not None and latest != current else None)
    by_component: dict[str, list[TraceRow]] = defaultdict(list)
    for trace in traces:
        if trace.component_id:
            by_component[trace.component_id].append(trace)
    found: list[Primitive] = []
    for key, kind in (("agents", "agent"), ("teams", "team"), ("workflows", "workflow")):
        for raw in cast("list[Any]", config.get(key) or []):
            if not isinstance(raw, dict):
                continue
            entry = cast("dict[str, Any]", raw)
            component_id = str(entry.get("id") or entry.get(f"{kind}_id") or "")
            if not component_id:
                continue
            live, draft = versions.get(component_id, (_int(entry.get("current_version")), None))
            runs = by_component.get(component_id, [])
            starts = [trace.start for trace in runs if trace.start is not None]
            found.append(
                Primitive(
                    id=component_id,
                    kind=cast("Kind", kind),
                    name=str(entry.get("name") or component_id),
                    live_version=live,
                    draft_version=draft,
                    runs=len(runs),
                    errors=sum(1 for trace in runs if trace.failed),
                    last_run_at=max(starts) if starts else None,
                )
            )
    found.sort(key=lambda item: (-item.runs, item.kind, item.name))
    return found


def component_counts(config: Mapping[str, Any]) -> dict[str, int]:
    return {key: len(cast("list[Any]", config.get(key) or [])) for key in ("agents", "teams", "workflows")}


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
