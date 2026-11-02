"""Dependency wiring of the observe module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_observe.application.cache import OverviewCache
from agnostic_observe.application.calls import PersonCalls
from agnostic_observe.application.metrics import (
    EffectivePrices,
    GetMetricsSummary,
    GetPriceTable,
    ReplacePriceTable,
)
from agnostic_observe.application.overview import BuildOverview, GetOverview, WarmOverviews
from agnostic_observe.application.ports import ComparisonStore, PriceRepository
from agnostic_observe.application.traces import CompareTrace, GetSpanStats
from agnostic_observe.infrastructure.repository import SqlComparisonStore, SqlPriceRepository
from agnostic_observe.settings import ObserveSettings


class ObserveProvider(Provider):
    scope = Scope.REQUEST

    cache = provide(OverviewCache)
    get_overview = provide(GetOverview)
    warm = provide(WarmOverviews)
    calls = provide(PersonCalls)
    prices = provide(SqlPriceRepository, provides=PriceRepository)
    comparisons = provide(SqlComparisonStore, provides=ComparisonStore)
    effective_prices = provide(EffectivePrices)
    get_price_table = provide(GetPriceTable)
    replace_price_table = provide(ReplacePriceTable)

    @provide
    def build(self, instances: InstancesFacade, settings: ObserveSettings) -> BuildOverview:
        return BuildOverview(instances, settings.max_trace_pages)

    @provide
    def compare_trace(self, calls: PersonCalls, store: ComparisonStore, settings: ObserveSettings) -> CompareTrace:
        return CompareTrace(calls, store, settings.comparison_cache_days)

    @provide
    def span_stats(
        self,
        calls: PersonCalls,
        instances: InstancesFacade,
        authorizer: Authorizer,
        store: EphemeralStore,
        settings: ObserveSettings,
    ) -> GetSpanStats:
        return GetSpanStats(
            calls, instances, authorizer, store, settings.max_span_stat_traces, settings.span_stats_ttl_seconds
        )

    @provide
    def metrics_summary(
        self, calls: PersonCalls, prices: EffectivePrices, settings: ObserveSettings
    ) -> GetMetricsSummary:
        return GetMetricsSummary(calls, prices, settings.max_session_pages, settings.max_trace_pages)
