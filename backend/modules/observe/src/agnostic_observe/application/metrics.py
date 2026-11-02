"""The Metrics page: daily aggregates, per-component usage, model usage and cost from the price table."""

from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import AppError, ValidationFailedError
from agnostic_observe.application.calls import PersonCalls, page_items
from agnostic_observe.application.ports import PriceEntry, PriceRepository
from agnostic_observe.domain.costs import Price, Tokens, merged_prices
from agnostic_observe.domain.metrics import (
    ComponentUsage,
    DayRow,
    ModelRuns,
    SessionUsage,
    SummaryCost,
    Totals,
    components,
    day_rows,
    model_usage,
    summary_cost,
    totals,
)
from agnostic_observe.domain.overview import TraceRow, parse_time

MAX_RANGE_DAYS = 92
PAGE = 100


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    instance_id: str
    first: date
    last: date
    generated_at: datetime
    last_aggregated_at: datetime | None
    days: list[DayRow]
    totals: Totals
    model_usage: list[ModelRuns]
    components: list[ComponentUsage]
    gap: Tokens
    """Tokens in the daily totals that the range's sessions don't explain (priced by model run share)."""
    prices: list[PriceEntry]
    cost: SummaryCost
    sampled: bool
    unavailable: dict[str, str] = field(default_factory=dict[str, str])


def date_range(first: date | None, last: date | None, today: date) -> tuple[date, date]:
    last = last or today
    first = first or last - timedelta(days=6)
    if first > last:
        raise ValidationFailedError("The range starts after it ends.")
    if (last - first).days >= MAX_RANGE_DAYS:
        raise ValidationFailedError(f"Pick at most {MAX_RANGE_DAYS} days.")
    return first, last


class EffectivePrices:
    def __init__(self, prices: PriceRepository) -> None:
        self._prices = prices

    async def __call__(self, instance_id: str) -> list[PriceEntry]:
        org, own = await self._prices.rows(None), await self._prices.rows(instance_id)
        effective = merged_prices([entry.price for entry in org], [entry.price for entry in own])
        by_price = {id(entry.price): entry for entry in (*org, *own)}
        return [by_price[id(price)] for price in effective]


async def _optional(call: Callable[[], Awaitable[Any]]) -> Any:  # noqa: ANN401
    try:
        return await call()
    except AppError as exc:
        return exc


class GetMetricsSummary:
    def __init__(
        self, calls: PersonCalls, prices: EffectivePrices, max_session_pages: int, max_trace_pages: int
    ) -> None:
        self._calls = calls
        self._prices = prices
        self._max_session_pages = max_session_pages
        self._max_trace_pages = max_trace_pages

    async def __call__(
        self, principal: Principal, instance_ref: str, first: date | None, last: date | None
    ) -> MetricsSummary:
        now = utcnow()
        start, end = date_range(first, last, now.date())
        instance = await self._calls.instance(instance_ref)
        window = (datetime.combine(start, time.min, UTC), datetime.combine(end + timedelta(days=1), time.min, UTC))
        params: dict[str, str | int] = {"starting_date": start.isoformat(), "ending_date": end.isoformat()}
        metrics = await self._calls.json(principal, instance, "/metrics", params=params)
        sessions, traces = await asyncio.gather(
            _optional(lambda: self._sessions(principal, instance, window)),
            _optional(lambda: self._traces(principal, instance, window)),
        )
        unavailable: dict[str, str] = {}
        session_items: list[SessionUsage] | None = None
        sampled = False
        if isinstance(sessions, AppError):
            unavailable["components"] = sessions.detail or sessions.title
        else:
            session_items, sampled = cast("tuple[list[SessionUsage], bool]", sessions)
        trace_rows: list[TraceRow] | None = None
        if isinstance(traces, AppError):
            unavailable["component_runs"] = traces.detail or traces.title
        else:
            trace_rows, more = cast("tuple[list[TraceRow], bool]", traces)
            sampled = sampled or more

        days = day_rows(metrics, start, end)
        usage = model_usage(days)
        items = components(session_items or [], trace_rows)
        total = totals(days, session_items)
        covered = sum((session.tokens for session in session_items or []), Tokens())
        gap = total.tokens.minus(covered)
        prices = await self._prices(instance.id)
        return MetricsSummary(
            instance_id=instance.id,
            first=start,
            last=end,
            generated_at=now,
            last_aggregated_at=parse_time(cast("dict[str, Any]", metrics).get("updated_at"))
            if isinstance(metrics, dict)
            else None,
            days=days,
            totals=total,
            model_usage=usage,
            components=items,
            gap=gap,
            prices=prices,
            cost=summary_cost(items, gap, usage, [entry.price for entry in prices]),
            sampled=sampled,
            unavailable=unavailable,
        )

    async def _sessions(
        self, principal: Principal, instance: Instance, window: tuple[datetime, datetime]
    ) -> tuple[list[SessionUsage], bool]:
        """Sessions active in the range, newest activity first; ``True`` when the page cap cut the scan short."""
        found: list[SessionUsage] = []
        for page in range(1, self._max_session_pages + 1):
            params: dict[str, str | int] = {"sort_by": "updated_at", "sort_order": "desc", "limit": PAGE, "page": page}
            items, _ = page_items(await self._calls.json(principal, instance, "/sessions", params=params))
            done = len(items) < PAGE
            for item in items:
                session = SessionUsage.parse(item)
                if session.active_at is None or session.active_at >= window[1]:
                    continue
                if session.active_at < window[0]:
                    done = True
                    break
                found.append(session)
            if done:
                return found, False
        return found, True

    async def _traces(
        self, principal: Principal, instance: Instance, window: tuple[datetime, datetime]
    ) -> tuple[list[TraceRow], bool]:
        rows: list[TraceRow] = []
        for page in range(1, self._max_trace_pages + 1):
            params: dict[str, str | int] = {
                "start_time": window[0].isoformat(),
                "end_time": window[1].isoformat(),
                "page": page,
                "limit": PAGE,
            }
            items, _ = page_items(await self._calls.json(principal, instance, "/traces", params=params))
            rows.extend(TraceRow.parse(item) for item in items)
            if len(items) < PAGE:
                return rows, False
        return rows, True


CSV_HEADER = (
    "component",
    "type",
    "primary_model",
    "extra_models",
    "runs",
    "sessions",
    "input_tokens",
    "cache_read_tokens",
    "output_tokens",
    "reasoning_tokens",
    "estimated_cost_usd",
    "approximate",
)


def summary_csv(summary: MetricsSummary) -> str:
    costs = {row.component_id: row for row in summary.cost.components}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for item in summary.components:
        row = costs.get(item.id)
        primary = item.primary_model
        writer.writerow(
            (
                item.id,
                item.kind,
                primary.model_id if primary else "",
                item.extra_models,
                "" if item.runs is None else item.runs,
                item.sessions,
                item.tokens.input,
                item.tokens.cache_read,
                item.tokens.output,
                item.tokens.reasoning,
                f"{row.amount:.4f}" if row else "",
                "yes" if row and row.approximate else "no",
            )
        )
    return buffer.getvalue()


class GetPriceTable:
    def __init__(self, calls: PersonCalls, authorizer: Authorizer, prices: EffectivePrices) -> None:
        self._calls = calls
        self._authorizer = authorizer
        self._prices = prices

    async def __call__(self, principal: Principal, instance_ref: str) -> list[PriceEntry]:
        instance = await self._calls.instance(instance_ref)
        _ = await self._authorizer.require(principal, "metrics:read", instance_id=instance.id)
        return await self._prices(instance.id)


def _check(prices: Sequence[Price]) -> None:
    seen: set[tuple[str, str]] = set()
    for price in prices:
        key = (price.model_id.lower(), (price.provider or "").lower())
        if key in seen:
            raise ValidationFailedError(f"{price.model_id} is listed twice.")
        seen.add(key)


class ReplacePriceTable:
    """Instance overrides (``metrics:write`` on it) or the org defaults (``org:write``)."""

    def __init__(
        self,
        calls: PersonCalls,
        authorizer: Authorizer,
        prices: PriceRepository,
        effective: EffectivePrices,
        audit: AuditLog,
    ) -> None:
        self._calls = calls
        self._authorizer = authorizer
        self._prices = prices
        self._effective = effective
        self._audit = audit

    async def instance(self, principal: Principal, instance_ref: str, rows: Sequence[Price]) -> list[PriceEntry]:
        instance = await self._calls.instance(instance_ref)
        _ = await self._authorizer.require(principal, "metrics:write", instance_id=instance.id)
        await self._save(principal, instance.id, instance.display_name, rows)
        return await self._effective(instance.id)

    async def org(self, principal: Principal, rows: Sequence[Price]) -> list[PriceEntry]:
        _ = await self._authorizer.require(principal, "org:write")
        await self._save(principal, None, "the org", rows)
        return await self._prices.rows(None)

    async def _save(self, principal: Principal, instance_id: str | None, where: str, rows: Sequence[Price]) -> None:
        _check(rows)
        before = {entry.price.model_id: entry.price for entry in await self._prices.rows(instance_id)}
        after = {price.model_id: price for price in rows}
        await self._prices.replace(instance_id, rows, principal.id)
        _ = await self._audit.record(
            AuditEntry(
                action="observe.price_table.updated",
                actor=actor_of(principal),
                resource_kind="price_table",
                resource_id=instance_id or "org",
                resource_display=f"price table of {where}",
                instance_id=instance_id,
                fields={"where": where, "models": str(len(rows))},
                diff={
                    model: {"before": _rates(before.get(model)), "after": _rates(after.get(model))}
                    for model in sorted(before.keys() | after.keys())
                    if _rates(before.get(model)) != _rates(after.get(model))
                },
            )
        )
        await self._prices.commit()


def _rates(price: Price | None) -> list[float | None] | None:
    if price is None:
        return None
    return [price.input_per_1m, price.output_per_1m, price.cache_read_per_1m, price.reasoning_per_1m]
