"""Dependency wiring of the studio module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_studio.application.access import StudioAccess
from agnostic_studio.application.catalog import RegistryCatalog
from agnostic_studio.application.codegen import Codegen
from agnostic_studio.application.components import Components
from agnostic_studio.application.drafts import Drafts
from agnostic_studio.application.ports import StudioStore
from agnostic_studio.application.promotions import Promotions
from agnostic_studio.application.publishing import Publisher
from agnostic_studio.application.testing import DraftRuns
from agnostic_studio.application.validation import Validator
from agnostic_studio.infrastructure.repository import SqlStudioStore


class StudioProvider(Provider):
    scope = Scope.REQUEST

    store = provide(SqlStudioStore, provides=StudioStore)
    access = provide(StudioAccess)
    catalog = provide(RegistryCatalog)
    components = provide(Components)
    drafts = provide(Drafts)
    validator = provide(Validator)
    publisher = provide(Publisher)
    codegen = provide(Codegen)
    promotions = provide(Promotions)
    draft_runs = provide(DraftRuns)
