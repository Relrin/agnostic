"""Dependency wiring of the search module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_search.application.ports import SearchIndex
from agnostic_search.application.use_cases import SearchEntities
from agnostic_search.infrastructure.repository import SqlSearchIndex


class SearchModuleProvider(Provider):
    scope = Scope.REQUEST

    index = provide(SqlSearchIndex, provides=SearchIndex)
    search = provide(SearchEntities)
