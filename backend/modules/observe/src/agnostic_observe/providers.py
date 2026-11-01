"""Dependency wiring of the observe module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_instances.facade import InstancesFacade
from agnostic_observe.application.cache import OverviewCache
from agnostic_observe.application.overview import BuildOverview, GetOverview, WarmOverviews
from agnostic_observe.settings import ObserveSettings


class ObserveProvider(Provider):
    scope = Scope.REQUEST

    cache = provide(OverviewCache)
    get_overview = provide(GetOverview)
    warm = provide(WarmOverviews)

    @provide
    def build(self, instances: InstancesFacade, settings: ObserveSettings) -> BuildOverview:
        return BuildOverview(instances, settings.max_trace_pages)
