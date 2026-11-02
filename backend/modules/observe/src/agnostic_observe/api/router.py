"""HTTP routes: the Home overview, trace comparison and span statistics, metrics summary, price tables."""

from datetime import date
from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query
from fastapi.responses import Response

from agnostic_kernel.auth import Principal
from agnostic_observe.api.metrics_schemas import MetricsSummaryOut, PriceOut, PriceTableIn, PriceTableOut
from agnostic_observe.api.schemas import OverviewOut
from agnostic_observe.api.trace_schemas import SpanStatsOut, TraceComparisonOut
from agnostic_observe.application.metrics import GetMetricsSummary, GetPriceTable, ReplacePriceTable, summary_csv
from agnostic_observe.application.overview import GetOverview
from agnostic_observe.application.ports import PriceRepository
from agnostic_observe.application.traces import CompareTrace, GetSpanStats

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)

type Window = Literal["24h", "7d", "30d"]
FromDate = Annotated[date | None, Query(alias="from", description="First day (UTC); default: 6 days before `to`")]
ToDate = Annotated[date | None, Query(alias="to", description="Last day (UTC), inclusive; default: today")]


@router.get(
    "/{instance}/overview",
    summary="Home: what needs attention, KPIs, runs per day, model usage, primitives and recent activity",
)
async def overview(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetOverview],
    range: Window = "7d",  # noqa: A002  (the public query parameter name)
    refresh: bool = False,
) -> OverviewOut:
    return OverviewOut.from_domain(await use_case(principal, instance, range, refresh=refresh))


@router.get(
    "/{instance}/traces/span-stats",
    summary="Slowest span types: average duration per span name over the newest traces of a window (needs traces:read)",
)
async def span_stats(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetSpanStats],
    window: Window = "7d",
) -> SpanStatsOut:
    return SpanStatsOut.of(await use_case(principal, instance, window))


@router.get(
    "/{instance}/traces/{trace_id}/comparison",
    summary="Compare a trace with the last successful run of the same component: aligned spans and a diagnosis",
)
async def trace_comparison(
    instance: str, trace_id: str, principal: FromDishka[Principal], use_case: FromDishka[CompareTrace]
) -> TraceComparisonOut:
    return TraceComparisonOut.of(await use_case(principal, instance, trace_id))


@router.get(
    "/{instance}/metrics/summary",
    summary="Metrics page: daily aggregates, per-component usage, model usage and estimated cost",
)
async def metrics_summary(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetMetricsSummary],
    start: FromDate = None,
    end: ToDate = None,
) -> MetricsSummaryOut:
    return MetricsSummaryOut.of(await use_case(principal, instance, start, end))


@router.get(
    "/{instance}/metrics/export.csv",
    summary="Usage and estimated cost per component as CSV",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "One row per component"}},
)
async def metrics_csv(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetMetricsSummary],
    start: FromDate = None,
    end: ToDate = None,
) -> Response:
    summary = await use_case(principal, instance, start, end)
    filename = f"{instance}-components-{summary.first.isoformat()}-{summary.last.isoformat()}.csv"
    return Response(
        summary_csv(summary),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{instance}/price-table", summary="The effective price table: org defaults with this instance's overrides")
async def get_price_table(
    instance: str, principal: FromDishka[Principal], use_case: FromDishka[GetPriceTable]
) -> PriceTableOut:
    return PriceTableOut(prices=[PriceOut.of(entry) for entry in await use_case(principal, instance)])


@router.put(
    "/{instance}/price-table",
    summary="Replace this instance's price overrides (needs metrics:write); returns the effective table",
)
async def put_price_table(
    instance: str, body: PriceTableIn, principal: FromDishka[Principal], use_case: FromDishka[ReplacePriceTable]
) -> PriceTableOut:
    saved = await use_case.instance(principal, instance, [row.to_domain() for row in body.prices])
    return PriceTableOut(prices=[PriceOut.of(entry) for entry in saved])


@org_router.get("/price-table", summary="The org's default price table")
async def get_org_price_table(principal: FromDishka[Principal], prices: FromDishka[PriceRepository]) -> PriceTableOut:
    _ = principal  # any signed-in member may read the defaults
    return PriceTableOut(prices=[PriceOut.of(entry) for entry in await prices.rows(None)])


@org_router.put("/price-table", summary="Replace the org's default price table (needs org:write)")
async def put_org_price_table(
    body: PriceTableIn, principal: FromDishka[Principal], use_case: FromDishka[ReplacePriceTable]
) -> PriceTableOut:
    saved = await use_case.org(principal, [row.to_domain() for row in body.prices])
    return PriceTableOut(prices=[PriceOut.of(entry) for entry in saved])
