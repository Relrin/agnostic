"""Dependency wiring of the studio module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_observe.facade import StepStats
from agnostic_studio.application.access import StudioAccess
from agnostic_studio.application.catalog import RegistryCatalog
from agnostic_studio.application.codegen import Codegen
from agnostic_studio.application.components import Components
from agnostic_studio.application.drafts import Drafts
from agnostic_studio.application.ports import (
    NoPublishHold,
    NoToolCatalog,
    PublishHold,
    SourceRunner,
    StudioStore,
    ToolCatalogLookup,
)
from agnostic_studio.application.promotions import Promotions
from agnostic_studio.application.publishing import Publisher
from agnostic_studio.application.source import SourceCode
from agnostic_studio.application.testing import DraftRuns
from agnostic_studio.application.validation import Validator
from agnostic_studio.application.workflows import Workflows
from agnostic_studio.facade import StudioFacade, StudioFacadeImpl
from agnostic_studio.infrastructure.isolation import SourceWorkers
from agnostic_studio.infrastructure.repository import SqlStudioStore
from agnostic_studio.settings import StudioSettings


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
    source = provide(SourceCode)
    publish_hold = provide(NoPublishHold, provides=PublishHold)
    tool_catalog = provide(NoToolCatalog, provides=ToolCatalogLookup)
    facade = provide(StudioFacadeImpl, provides=StudioFacade)

    @provide(scope=Scope.APP)
    def workers(self, settings: StudioSettings) -> SourceRunner:
        return SourceWorkers(settings.source_isolation, settings.source_workers, settings.source_timeout_seconds)

    @provide
    def workflows(
        self,
        access: StudioAccess,
        validator: Validator,
        store: StudioStore,
        runner: SourceRunner,
        step_stats: StepStats,
    ) -> Workflows:
        return Workflows(access, validator, store, runner, step_stats)
