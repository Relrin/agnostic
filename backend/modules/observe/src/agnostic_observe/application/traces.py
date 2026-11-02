"""Trace comparison with the last successful run, and the slowest span types of an instance."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.logging import get_logger
from agnostic_observe.application.calls import PersonCalls, page_items
from agnostic_observe.application.ports import ComparisonStore
from agnostic_observe.domain.comparison import Comparison, ComparisonRow, Ghost, SpanGroup, compare
from agnostic_observe.domain.overview import RANGES, RangeName, TraceRow, Window, parse_time
from agnostic_observe.domain.span_stats import SpanTypeStat, span_type_stats
from agnostic_observe.domain.traces import SpanKind, TraceView, parse_trace

log = get_logger(__name__)

BASELINE_CANDIDATES = 20
VERSION_PROBES = 5
"""Candidate baselines whose details are fetched while looking for one with the same component version."""
DETAIL_CONCURRENCY = 8


@dataclass(frozen=True, slots=True)
class Baseline:
    trace_id: str
    name: str
    start: datetime | None
    duration_ms: float
    version: int | None


@dataclass(frozen=True, slots=True)
class TraceComparison:
    trace_id: str
    baseline: Baseline | None
    comparison: Comparison | None
    reason: str | None
    """Why there is no baseline."""
    cached: bool = False


def _group(value: object) -> SpanGroup | None:
    if not isinstance(value, list):
        return None
    count, total, maximum, errors, first = cast("list[Any]", value)
    return SpanGroup(int(count), float(total), float(maximum), int(errors), float(first))


def _encode_group(group: SpanGroup | None) -> list[float | int] | None:
    if group is None:
        return None
    return [group.count, group.total_ms, group.max_ms, group.errors, group.first_start_ms]


def encode(result: TraceComparison) -> dict[str, Any]:
    comparison, baseline = result.comparison, result.baseline
    assert comparison is not None
    assert baseline is not None
    return {
        "baseline": [baseline.trace_id, baseline.name, baseline.start, baseline.duration_ms, baseline.version],
        "durations": [comparison.current_duration_ms, comparison.baseline_duration_ms],
        "same": [comparison.same_version, comparison.same_input_shape],
        "rows": [
            [list(row.path), row.kind, _encode_group(row.baseline), _encode_group(row.current), row.state, row.leaf]
            for row in comparison.rows
        ],
        "ghosts": [[ghost.span_id, ghost.start_ms, ghost.duration_ms] for ghost in comparison.ghosts],
        "diagnosis": comparison.diagnosis,
    }


def decode(trace_id: str, value: Mapping[str, Any]) -> TraceComparison:
    baseline_id, name, start, duration, version = value["baseline"]
    current_ms, baseline_ms = value["durations"]
    same_version, same_shape = value["same"]
    comparison = Comparison(
        current_trace_id=trace_id,
        baseline_trace_id=str(baseline_id),
        current_duration_ms=float(current_ms),
        baseline_duration_ms=float(baseline_ms),
        same_version=same_version,
        same_input_shape=same_shape,
        rows=[
            ComparisonRow(tuple(path), cast("SpanKind", kind), _group(before), _group(after), state, bool(leaf))
            for path, kind, before, after, state, leaf in value["rows"]
        ],
        ghosts=[Ghost(str(span_id), float(start_ms), float(ms)) for span_id, start_ms, ms in value["ghosts"]],
        diagnosis=str(value["diagnosis"]),
    )
    baseline = Baseline(str(baseline_id), str(name), parse_time(start), float(duration), version)
    return TraceComparison(trace_id, baseline, comparison, None, cached=True)


class CompareTrace:
    """``GET …/traces/{trace_id}/comparison``: every AgentOS read is made as the viewer, cache hits included."""

    def __init__(self, calls: PersonCalls, store: ComparisonStore, cache_days: int) -> None:
        self._calls = calls
        self._store = store
        self._cache_days = cache_days

    async def __call__(self, principal: Principal, instance_ref: str, trace_id: str) -> TraceComparison:
        instance = await self._calls.instance(instance_ref)
        current = parse_trace(await self._calls.json(principal, instance, f"/traces/{trace_id}"))
        if current.component_id is None or current.component_kind is None:
            return TraceComparison(trace_id, None, None, "This trace isn't tied to an agent, team or workflow.")
        if current.start is None:
            return TraceComparison(trace_id, None, None, "This trace has no start time.")

        candidates = await self._candidates(principal, instance, current)
        if not candidates:
            return TraceComparison(
                trace_id, None, None, f"No successful run of {current.component_id} before this one."
            )
        baseline, details = await self._pick(principal, instance, current, candidates)
        newer_than = utcnow() - timedelta(days=self._cache_days)
        cached = await self._store.get(instance.id, trace_id, baseline.trace_id, newer_than=newer_than)
        if cached is not None:
            try:
                return decode(trace_id, cached)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("observe.comparison_cache_unreadable", trace=trace_id, error=str(exc))
        baseline_view = details or parse_trace(
            await self._calls.json(principal, instance, f"/traces/{baseline.trace_id}")
        )
        result = TraceComparison(
            trace_id,
            replace(baseline, version=baseline_view.version, duration_ms=baseline_view.duration_ms),
            compare(current, baseline_view),
            None,
        )
        await self._store.put(instance.id, trace_id, baseline.trace_id, encode(result))
        return result

    async def _candidates(self, principal: Principal, instance: Instance, current: TraceView) -> list[Baseline]:
        assert current.start is not None
        params: dict[str, str | int] = {
            f"{current.component_kind}_id": cast("str", current.component_id),
            "status": "OK",
            "end_time": current.start.isoformat(),
            "page": 1,
            "limit": BASELINE_CANDIDATES,
        }
        items, _ = page_items(await self._calls.json(principal, instance, "/traces", params=params))
        found: list[Baseline] = []
        for item in items:
            row = TraceRow.parse(item)
            if row.trace_id == current.trace_id or row.status.upper() != "OK" or row.error_count:
                continue
            if row.start is None or row.start >= current.start:
                continue
            found.append(Baseline(row.trace_id, str(item.get("name") or ""), row.start, row.duration_ms or 0.0, None))
        found.sort(key=lambda item: cast("datetime", item.start), reverse=True)
        return found

    async def _pick(
        self, principal: Principal, instance: Instance, current: TraceView, candidates: list[Baseline]
    ) -> tuple[Baseline, TraceView | None]:
        """The newest candidate, or the newest with the same version when the trace carries one."""
        if current.version is None:
            return candidates[0], None
        first: TraceView | None = None
        for candidate in candidates[:VERSION_PROBES]:
            view = parse_trace(await self._calls.json(principal, instance, f"/traces/{candidate.trace_id}"))
            first = first or view
            if view.version == current.version:
                return candidate, view
        return candidates[0], first


@dataclass(frozen=True, slots=True)
class SpanStats:
    window: RangeName
    generated_at: datetime
    traces_scanned: int
    sampled: bool
    stats: list[SpanTypeStat]
    cached: bool = False


type _Encoded = dict[str, Any]


class GetSpanStats:
    """Instance-wide aggregate (like the Home overview): computed as the control plane, cached, needs traces:read."""

    def __init__(
        self,
        calls: PersonCalls,
        instances: InstancesFacade,
        authorizer: Authorizer,
        store: EphemeralStore,
        max_traces: int,
        ttl: float,
    ) -> None:
        self._calls = calls
        self._instances = instances
        self._authorizer = authorizer
        self._store = store
        self._max_traces = max_traces
        self._ttl = ttl

    async def __call__(self, principal: Principal, instance_ref: str, window_name: RangeName) -> SpanStats:
        instance = await self._calls.instance(instance_ref)
        _ = await self._authorizer.require(principal, "traces:read", instance_id=instance.id)
        key = f"obs:spanstats:{instance.id}:{window_name}"
        raw = await self._store.get(key)
        if raw is not None:
            try:
                return _decode_stats(cast("_Encoded", orjson.loads(raw)))
            except KeyError, TypeError, ValueError, orjson.JSONDecodeError:
                pass
        stats = await self._compute(instance, window_name)
        await self._store.set(key, orjson.dumps(_encode_stats(stats)), ttl=self._ttl)
        return stats

    async def _system(self, instance: Instance, path: str, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401
        return await self._instances.system_call(instance, "GET", path, params=params)

    async def _compute(self, instance: Instance, window_name: RangeName) -> SpanStats:
        now = utcnow()
        window = Window(now - RANGES[window_name], now)
        ids: list[str] = []
        total: int | None = None
        page = 1
        while len(ids) < self._max_traces:
            limit = min(100, self._max_traces - len(ids))
            params: dict[str, str | int] = {
                "start_time": window.start.isoformat(),
                "end_time": window.end.isoformat(),
                "page": page,
                "limit": limit,
            }
            items, count = page_items(await self._system(instance, "/traces", params))
            total = count if count is not None else total
            ids.extend(str(item["trace_id"]) for item in items if item.get("trace_id"))
            if len(items) < limit:
                break
            page += 1
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def detail(trace_id: str) -> TraceView | None:
            async with semaphore:
                try:
                    return parse_trace(await self._system(instance, f"/traces/{trace_id}"))
                except AgentOSError as exc:
                    log.info("observe.span_stats_skip", trace=trace_id, error=str(exc))
                    return None

        views = [view for view in await asyncio.gather(*(detail(i) for i in ids)) if view is not None]
        return SpanStats(
            window=window_name,
            generated_at=now,
            traces_scanned=len(views),
            sampled=(total or len(ids)) > len(ids),
            stats=span_type_stats(view.spans for view in views),
        )


def _encode_stats(stats: SpanStats) -> _Encoded:
    return {
        "window": stats.window,
        "generated_at": stats.generated_at,
        "scanned": stats.traces_scanned,
        "sampled": stats.sampled,
        "stats": [[s.name, s.kind, s.avg_ms, s.count, s.errors] for s in stats.stats],
    }


def _decode_stats(value: _Encoded) -> SpanStats:
    return SpanStats(
        window=cast("RangeName", value["window"]),
        generated_at=cast("datetime", parse_time(value["generated_at"])),
        traces_scanned=int(value["scanned"]),
        sampled=bool(value["sampled"]),
        stats=[
            SpanTypeStat(str(name), cast("SpanKind", kind), float(avg), int(count), int(errors))
            for name, kind, avg, count, errors in value["stats"]
        ],
        cached=True,
    )
