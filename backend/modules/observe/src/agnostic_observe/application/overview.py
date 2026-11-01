"""``GET /api/v1/instances/{instance}/overview``: the Home page in one call.

The aggregate is computed as the control plane (system token) because it is instance-wide by nature, cached for 60 s
per (instance, range), and kept warm by a periodic job. Each caller then gets only the sections their scopes allow;
a source that is disabled or failing makes its section ``unavailable`` instead of failing the page.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from agnostic_agentos_client import AgentOSError, CapabilityDisabledError, InstanceUnreachableError
from agnostic_audit.facade import AuditReader
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError
from agnostic_kernel.logging import get_logger
from agnostic_observe.application.cache import OverviewCache
from agnostic_observe.application.model import Overview, TraceSample, Unavailable
from agnostic_observe.domain.attention import (
    ErrorFacts,
    Facts,
    PendingApprovals,
    ScheduleFacts,
    attention,
    consecutive_failures,
)
from agnostic_observe.domain.overview import (
    DayMetrics,
    Kpi,
    RangeName,
    TraceRow,
    Window,
    component_counts,
    in_window,
    metric_rows,
    model_usage,
    parse_time,
    percentile,
    primitives,
    runs_per_day,
)

log = get_logger(__name__)

TRACE_PAGE = 100
MAX_SCHEDULES = 20
ACTIVITY_ACTIONS = ("approvals.*", "instances.*", "access.*", "gateway.elevated", "gateway.denied")

SECTION_SCOPES: Mapping[str, str] = {
    "kpis": "metrics:read",
    "runs_per_day": "metrics:read",
    "model_usage": "metrics:read",
    "primitives": "config:read",
    "counts": "config:read",
    "approvals": "approvals:read",
    "errors": "traces:read",
    "schedules": "schedules:read",
}


def _page_items(payload: object) -> tuple[list[dict[str, Any]], int | None]:
    """AgentOS lists come as ``{data, meta}`` or plain arrays."""
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        return [cast("dict[str, Any]", i) for i in items if isinstance(i, dict)], len(items)
    if isinstance(payload, dict):
        body = cast("dict[str, Any]", payload)
        data = cast("list[Any]", body.get("data") or [])
        meta = cast("dict[str, Any]", body.get("meta") or {})
        total = meta.get("total_count")
        return [cast("dict[str, Any]", i) for i in data if isinstance(i, dict)], int(
            total
        ) if total is not None else None
    return [], None


class BuildOverview:
    """Computes the full (unfiltered) overview of one instance, as the control plane."""

    def __init__(self, instances: InstancesFacade, max_trace_pages: int) -> None:
        self._instances = instances
        self._max_pages = max_trace_pages

    async def _get(self, instance: Instance, path: str, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401
        try:
            return await self._instances.system_call(instance, "GET", path, params=params)
        except CapabilityDisabledError as exc:
            raise Unavailable("Not enabled on this instance.") from exc
        except InstanceUnreachableError as exc:
            raise Unavailable("The instance didn't answer.") from exc
        except AgentOSError as exc:
            raise Unavailable(f"The instance answered HTTP {exc.status}.") from exc

    async def __call__(self, instance: Instance, range_name: RangeName, now: datetime | None = None) -> Overview:
        now = now or utcnow()
        window = Window.of(range_name, now)
        overview = Overview(instance_id=instance.id, range=range_name, window=window, generated_at=now)
        both = Window(window.previous.start, window.end)

        config, metrics, traces, previous, components, approvals, schedules = await asyncio.gather(
            self._safe(lambda: self._get(instance, "/config")),
            self._safe(
                lambda: self._get(
                    instance,
                    "/metrics",
                    {"starting_date": both.start.date().isoformat(), "ending_date": both.end.date().isoformat()},
                )
            ),
            self._safe(lambda: self._traces(instance, window)),
            self._safe(lambda: self._trace_totals(instance, window.previous)),
            self._safe(lambda: self._get(instance, "/components", {"limit": 200})),
            self._safe(lambda: self._approvals(instance)),
            self._safe(lambda: self._schedules(instance)),
        )

        sample = traces if isinstance(traces, TraceSample) else None
        if isinstance(config, Unavailable):
            overview.unavailable["primitives"] = config.reason
        else:
            body = cast("dict[str, Any]", config) if isinstance(config, dict) else {}
            component_items = [] if isinstance(components, Unavailable) else _page_items(components)[0]
            overview.counts = component_counts(body)
            overview.primitives = primitives(body, component_items, sample.rows if sample else [])

        rows: list[DayMetrics] = [] if isinstance(metrics, Unavailable) else metric_rows(metrics)
        if isinstance(metrics, Unavailable):
            overview.unavailable["metrics"] = metrics.reason
        current_rows, previous_rows = in_window(rows, window), in_window(rows, window.previous)

        if sample is None:
            overview.unavailable["errors"] = cast("Unavailable", traces).reason
        totals = cast("tuple[int, int]", previous) if isinstance(previous, tuple) else None
        overview.kpis = self._kpis(current_rows, previous_rows, sample, totals)
        overview.runs_per_day = runs_per_day(current_rows, sample.rows if sample else [], window)
        overview.model_usage = model_usage(current_rows)
        overview.sampled = bool(sample and sample.truncated)
        if sample is not None:
            prev_runs, prev_failed = totals or (0, 0)
            failed_rows = [row for row in sample.rows if row.failed]
            worst = Counter(row.component_id for row in failed_rows if row.component_id).most_common(1)
            latest = max(failed_rows, key=lambda row: row.start or now, default=None)
            overview.errors = ErrorFacts(
                runs=sample.total,
                failed=sample.failed_total,
                previous_runs=prev_runs,
                previous_failed=prev_failed,
                worst_component=worst[0][0] if worst else None,
                latest_failed_trace=latest.trace_id if latest else None,
            )

        if isinstance(approvals, Unavailable):
            overview.unavailable["approvals"] = approvals.reason
        else:
            overview.approvals = cast("PendingApprovals", approvals)
        if isinstance(schedules, Unavailable):
            overview.unavailable["schedules"] = schedules.reason
        else:
            overview.schedules = cast("list[ScheduleFacts]", schedules)

        overview.attention = attention(
            Facts(now=now, approvals=overview.approvals, errors=overview.errors, schedules=overview.schedules or ())
        )
        return overview

    @staticmethod
    async def _safe(call: Callable[[], Awaitable[Any]]) -> Any:  # noqa: ANN401
        try:
            return await call()
        except Unavailable as exc:
            return exc

    @staticmethod
    def _kpis(
        current: Sequence[DayMetrics],
        previous: Sequence[DayMetrics],
        sample: TraceSample | None,
        previous_traces: tuple[int, int] | None,
    ) -> dict[str, Kpi]:
        runs_now = sum(row.runs for row in current) if current else (sample.total if sample else None)
        runs_before = (
            sum(row.runs for row in previous) if previous else (previous_traces[0] if previous_traces else None)
        )
        kpis = {
            "runs": Kpi(runs_now, runs_before),
            "sessions": Kpi(
                sum(row.sessions for row in current) if current else None,
                sum(row.sessions for row in previous) if previous else None,
            ),
        }
        if sample is not None:
            rate = sample.failed_total / sample.total if sample.total else None
            prev_rate = previous_traces[1] / previous_traces[0] if previous_traces and previous_traces[0] else None
            durations = [row.duration_ms for row in sample.rows if row.duration_ms is not None]
            kpis["error_rate"] = Kpi(rate, prev_rate)
            kpis["failed_runs"] = Kpi(sample.failed_total, previous_traces[1] if previous_traces else None)
            kpis["p95_latency_ms"] = Kpi(percentile(durations, 0.95), None)
        return kpis

    async def _trace_page(
        self, instance: Instance, window: Window, page: int, status: str | None = None, limit: int = TRACE_PAGE
    ) -> tuple[list[dict[str, Any]], int | None]:
        params: dict[str, str | int] = {
            "start_time": window.start.isoformat(),
            "end_time": window.end.isoformat(),
            "page": page,
            "limit": limit,
        }
        if status:
            params["status"] = status
        return _page_items(await self._get(instance, "/traces", params))

    async def _traces(self, instance: Instance, window: Window) -> TraceSample:
        rows: list[TraceRow] = []
        total: int | None = None
        truncated = False
        for page in range(1, self._max_pages + 1):
            items, count = await self._trace_page(instance, window, page)
            total = count if count is not None else total
            rows.extend(TraceRow.parse(item) for item in items)
            if len(items) < TRACE_PAGE:
                break
        else:
            truncated = True
        failed_items, failed_total = await self._trace_page(instance, window, 1, status="ERROR", limit=1)
        failed = failed_total if failed_total is not None else len(failed_items)
        if not truncated:
            failed = max(failed, sum(1 for row in rows if row.failed))
        return TraceSample(rows, total if total is not None else len(rows), failed, truncated)

    async def _trace_totals(self, instance: Instance, window: Window) -> tuple[int, int]:
        items, total = await self._trace_page(instance, window, 1, limit=1)
        failed_items, failed = await self._trace_page(instance, window, 1, status="ERROR", limit=1)
        return (total if total is not None else len(items), failed if failed is not None else len(failed_items))

    async def _approvals(self, instance: Instance) -> PendingApprovals:
        items, total = _page_items(await self._get(instance, "/approvals", {"status": "pending", "limit": 100}))
        created = [moment for item in items if (moment := parse_time(item.get("created_at"))) is not None]
        tools = Counter(str(item["tool_name"]) for item in items if item.get("tool_name"))
        top_tool = tools.most_common(1)[0][0] if tools else None
        component = next(
            (
                str(item.get("agent_id") or item.get("team_id") or item.get("workflow_id"))
                for item in items
                if item.get("tool_name") == top_tool
                and (item.get("agent_id") or item.get("team_id") or item.get("workflow_id"))
            ),
            None,
        )
        return PendingApprovals(
            count=total if total is not None else len(items),
            oldest_created_at=min(created) if created else None,
            top_tool=top_tool,
            top_component=component,
        )

    async def _schedules(self, instance: Instance) -> list[ScheduleFacts]:
        items, _ = _page_items(await self._get(instance, "/schedules", {"limit": 100}))
        enabled = [item for item in items if item.get("enabled", True)][:MAX_SCHEDULES]
        facts: list[ScheduleFacts] = []
        for item in enabled:
            schedule_id = str(item.get("id") or "")
            try:
                runs, _ = _page_items(await self._get(instance, f"/schedules/{schedule_id}/runs", {"limit": 5}))
            except Unavailable:
                continue
            runs.sort(
                key=lambda run: parse_time(run.get("triggered_at") or run.get("created_at")) or utcnow(), reverse=True
            )
            failures = consecutive_failures([str(run.get("status") or "") for run in runs])
            latest = runs[0] if runs else {}
            facts.append(
                ScheduleFacts(
                    schedule_id=schedule_id,
                    name=str(item.get("name") or schedule_id),
                    consecutive_failures=failures,
                    last_error=str(latest["error"])[:160] if failures and latest.get("error") else None,
                    last_failed_at=parse_time(latest.get("completed_at") or latest.get("triggered_at"))
                    if failures
                    else None,
                    run_id=str(latest["run_id"]) if failures and latest.get("run_id") else None,
                )
            )
        return facts


class GetOverview:
    def __init__(
        self,
        instances: InstancesFacade,
        authorizer: Authorizer,
        build: BuildOverview,
        cache: OverviewCache,
        audit: AuditReader,
    ) -> None:
        self._instances = instances
        self._authorizer = authorizer
        self._build = build
        self._cache = cache
        self._audit = audit

    async def __call__(
        self, principal: Principal, instance_ref: str, range_name: RangeName, *, refresh: bool = False
    ) -> Overview:
        instance = await self._instances.get(instance_ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {instance_ref!r}.")
        if instance.status is InstanceStatus.DISABLED:
            raise ConflictError(f"{instance.display_name} is disabled.")
        _ = await self._authorizer.require(principal, "os:read", instance_id=instance.id)

        overview = None if refresh else await self._cache.get(instance.id, range_name)
        if overview is None:
            overview = await self._build(instance, range_name)
            await self._cache.put(overview)
        else:
            overview = replace(overview, cached=True)
        return await self._filtered(principal, instance, overview)

    async def _filtered(self, principal: Principal, instance: Instance, overview: Overview) -> Overview:
        allowed: dict[str, bool] = {}
        result = replace(overview, unavailable=dict(overview.unavailable))
        for section, scope in SECTION_SCOPES.items():
            allowed[section] = (await self._authorizer.check(principal, scope, instance_id=instance.id)).allowed
            if not allowed[section]:
                result.unavailable[section] = f"You don't have {scope} on {instance.display_name}."
        _hide(result, allowed)
        result.attention = attention(
            Facts(
                now=overview.generated_at,
                approvals=result.approvals,
                errors=result.errors,
                schedules=result.schedules or (),
            )
        )
        if (await self._authorizer.check(principal, "audit:read")).allowed:
            result.activity = await self._audit.recent(instance_id=instance.id, actions=ACTIVITY_ACTIONS, limit=8)
        else:
            result.unavailable["activity"] = "You don't have audit:read."
        return result


def _hide(result: Overview, allowed: Mapping[str, bool]) -> None:
    """Drop the sections the viewer's scopes don't cover (in place)."""
    trace_kpis = {"error_rate", "failed_runs", "p95_latency_ms"}
    if not allowed["kpis"]:
        kpis = result.kpis or {}
        result.kpis = {k: v for k, v in kpis.items() if k in trace_kpis} if allowed["errors"] else None
        result.runs_per_day = None
        result.model_usage = None
    elif not allowed["errors"] and result.kpis is not None:
        result.kpis = {k: v for k, v in result.kpis.items() if k not in trace_kpis}
    if not allowed["primitives"]:
        result.primitives = None
        result.counts = None
    if not allowed["approvals"]:
        result.approvals = None
    if not allowed["errors"]:
        result.errors = None
    if not allowed["schedules"]:
        result.schedules = None


class WarmOverviews:
    """Periodic job body: recompute the default range for every connected instance."""

    def __init__(self, instances: InstancesFacade, build: BuildOverview, cache: OverviewCache) -> None:
        self._instances = instances
        self._build = build
        self._cache = cache

    async def __call__(self, range_name: RangeName = "7d") -> int:
        warmed = 0
        for instance in await self._instances.list():
            if instance.status is not InstanceStatus.CONNECTED:
                continue
            try:
                await self._cache.put(await self._build(instance, range_name))
                warmed += 1
            except Exception as exc:  # noqa: BLE001  (one bad instance must not stop the others)
                log.warning("observe.warm_failed", instance=instance.id, error=str(exc))
        return warmed
