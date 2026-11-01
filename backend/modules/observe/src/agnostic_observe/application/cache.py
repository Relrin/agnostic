"""60-second cache of computed overviews in the ephemeral store (shared across replicas)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, cast

import orjson

from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_observe.application.model import Overview
from agnostic_observe.domain.attention import Action, AttentionItem, ErrorFacts, PendingApprovals, ScheduleFacts
from agnostic_observe.domain.overview import DayRuns, Kpi, ModelShare, Primitive, RangeName, Window

CACHE_TTL = 60.0


def _dt(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def encode(overview: Overview) -> bytes:
    """Everything except the per-viewer parts (activity, the ``cached`` flag)."""
    return orjson.dumps(
        {
            "instance_id": overview.instance_id,
            "range": overview.range,
            "window": [overview.window.start, overview.window.end],
            "generated_at": overview.generated_at,
            "counts": overview.counts,
            "kpis": {k: [v.value, v.previous] for k, v in overview.kpis.items()} if overview.kpis is not None else None,
            "runs_per_day": [[r.day, r.completed, r.failed] for r in overview.runs_per_day]
            if overview.runs_per_day is not None
            else None,
            "model_usage": [[m.model_id, m.runs, m.share] for m in overview.model_usage]
            if overview.model_usage is not None
            else None,
            "primitives": [
                [p.id, p.kind, p.name, p.live_version, p.draft_version, p.runs, p.errors, p.last_run_at]
                for p in overview.primitives
            ]
            if overview.primitives is not None
            else None,
            "approvals": [
                overview.approvals.count,
                overview.approvals.oldest_created_at,
                overview.approvals.top_tool,
                overview.approvals.top_component,
            ]
            if overview.approvals is not None
            else None,
            "errors": [
                overview.errors.runs,
                overview.errors.failed,
                overview.errors.previous_runs,
                overview.errors.previous_failed,
                overview.errors.worst_component,
                overview.errors.latest_failed_trace,
            ]
            if overview.errors is not None
            else None,
            "schedules": [
                [s.schedule_id, s.name, s.consecutive_failures, s.last_error, s.last_failed_at, s.run_id]
                for s in overview.schedules
            ]
            if overview.schedules is not None
            else None,
            "attention": [
                [
                    a.key,
                    a.kind,
                    a.severity,
                    a.title,
                    a.detail,
                    [a.action.label, a.action.target] if a.action else None,
                ]
                for a in overview.attention
            ],
            "unavailable": overview.unavailable,
            "sampled": overview.sampled,
        }
    )


def decode(raw: bytes) -> Overview:
    value = cast("dict[str, Any]", orjson.loads(raw))
    start, end = value["window"]
    overview = Overview(
        instance_id=str(value["instance_id"]),
        range=cast("RangeName", value["range"]),
        window=Window(cast("datetime", _dt(start)), cast("datetime", _dt(end))),
        generated_at=cast("datetime", _dt(value["generated_at"])),
        counts=value.get("counts"),
        unavailable=dict(value.get("unavailable") or {}),
        sampled=bool(value.get("sampled")),
    )
    if (kpis := value.get("kpis")) is not None:
        overview.kpis = {k: Kpi(v[0], v[1]) for k, v in kpis.items()}
    if (days := value.get("runs_per_day")) is not None:
        overview.runs_per_day = [DayRuns(date.fromisoformat(d), c, f) for d, c, f in days]
    if (models := value.get("model_usage")) is not None:
        overview.model_usage = [ModelShare(m, r, s) for m, r, s in models]
    if (items := value.get("primitives")) is not None:
        overview.primitives = [
            Primitive(i, k, n, live, draft, runs, errors, _dt(last))
            for i, k, n, live, draft, runs, errors, last in items
        ]
    if (approvals := value.get("approvals")) is not None:
        overview.approvals = PendingApprovals(approvals[0], _dt(approvals[1]), approvals[2], approvals[3])
    if (errors := value.get("errors")) is not None:
        overview.errors = ErrorFacts(*errors)
    if (schedules := value.get("schedules")) is not None:
        overview.schedules = [ScheduleFacts(a, b, c, d, _dt(e), f) for a, b, c, d, e, f in schedules]
    attention_rows = cast("list[list[Any]]", value.get("attention") or [])
    overview.attention = [
        AttentionItem(row[0], row[1], row[2], row[3], row[4], Action(row[5][0], row[5][1]) if row[5] else None)
        for row in attention_rows
    ]
    return overview


class OverviewCache:
    def __init__(self, store: EphemeralStore) -> None:
        self._store = store

    @staticmethod
    def key(instance_id: str, range_name: RangeName) -> str:
        return f"obs:overview:{instance_id}:{range_name}"

    async def get(self, instance_id: str, range_name: RangeName) -> Overview | None:
        raw = await self._store.get(self.key(instance_id, range_name))
        if raw is None:
            return None
        try:
            return decode(raw)
        except orjson.JSONDecodeError, KeyError, TypeError, ValueError:
            return None

    async def put(self, overview: Overview) -> None:
        await self._store.set(self.key(overview.instance_id, overview.range), encode(overview), ttl=CACHE_TTL)
