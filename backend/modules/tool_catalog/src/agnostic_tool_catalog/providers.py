"""Dependency wiring of the tool catalog module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_audit.facade import AuditLog
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.settings import Settings
from agnostic_service_accounts.facade import ServiceAccountsFacade
from agnostic_studio.facade import ToolCatalogLookup
from agnostic_tool_catalog.application.catalog import CatalogAccess, CatalogViews, ToolCatalog
from agnostic_tool_catalog.application.ports import (
    EntryRepository,
    NotifyQueue,
    RuntimeBridge,
    SyncStateRepository,
)
from agnostic_tool_catalog.application.sync import CatalogLookup, CatalogSync, ManifestReader
from agnostic_tool_catalog.application.toolkits import Toolkits
from agnostic_tool_catalog.infrastructure.repository import SqlEntryRepository, SqlSyncStateRepository
from agnostic_tool_catalog.infrastructure.runtime import BridgeClient, JobNotifyQueue


class ToolCatalogProvider(Provider):
    scope = Scope.REQUEST

    entries = provide(SqlEntryRepository, provides=EntryRepository)
    states = provide(SqlSyncStateRepository, provides=SyncStateRepository)
    bridge = provide(BridgeClient, provides=RuntimeBridge)
    notify = provide(JobNotifyQueue, provides=NotifyQueue)
    access = provide(CatalogAccess)
    views = provide(CatalogViews)
    catalog = provide(ToolCatalog)
    manifests = provide(ManifestReader)
    lookup = provide(CatalogLookup, provides=ToolCatalogLookup, override=True)

    @provide(scope=Scope.APP)
    def toolkits(self) -> Toolkits:
        return Toolkits()

    @provide
    def sync(
        self,
        authorizer: Authorizer,
        access: CatalogAccess,
        instances: InstancesFacade,
        entries: EntryRepository,
        states: SyncStateRepository,
        bridge: RuntimeBridge,
        accounts: ServiceAccountsFacade,
        audit: AuditLog,
        toolkits: Toolkits,
        settings: Settings,
    ) -> CatalogSync:
        return CatalogSync(
            authorizer, access, instances, entries, states, bridge, accounts, audit, toolkits, settings.public_url()
        )
