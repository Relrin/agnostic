"""Dependency wiring of the audit module."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator

import procrastinate
from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agnostic_audit.application.archive import Archives, MaintainPartitions, VerifyChain
from agnostic_audit.application.exports import Exports
from agnostic_audit.application.policy import PolicyCache, PolicyService, policy_from
from agnostic_audit.application.ports import (
    ArchiveRepository,
    AuditRepository,
    DeliveryLock,
    ExportRepository,
    IngestCursorRepository,
    Jobs,
    ObjectStores,
    PartitionMaintenance,
    PolicyStore,
    SinkRepository,
    SinkTransport,
    StandaloneAuditWriter,
    UnitOfWork,
    ViewRepository,
)
from agnostic_audit.application.streaming import DeliverSinks, SinkService, StreamTrigger
from agnostic_audit.application.use_cases import (
    AuditVocabulary,
    GetEvent,
    ListActors,
    ListEvents,
    RecordEvent,
)
from agnostic_audit.application.views import SavedViews
from agnostic_audit.domain.governance import Policy
from agnostic_audit.facade import (
    AuditAdmin,
    AuditAdminImpl,
    AuditLog,
    AuditLogImpl,
    AuditReader,
    AuditReaderImpl,
    IngestCursors,
    IngestCursorsImpl,
)
from agnostic_audit.infrastructure.governance import (
    SqlArchiveRepository,
    SqlExportRepository,
    SqlIngestCursorRepository,
    SqlPolicyStore,
    SqlSinkRepository,
    SqlUnitOfWork,
    SqlViewRepository,
    any_enabled_sink,
)
from agnostic_audit.infrastructure.http import AuditHttp
from agnostic_audit.infrastructure.object_store import S3ObjectStores
from agnostic_audit.infrastructure.queue import ProcrastinateJobs
from agnostic_audit.infrastructure.repository import (
    SqlAuditRepository,
    SqlPartitionMaintenance,
    SqlStandaloneAuditWriter,
)
from agnostic_audit.infrastructure.sinks import SinkTransports, SqlDeliveryLock
from agnostic_audit.settings import AuditSettings
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.jobs import JobQueue
from agnostic_kernel.modules import LoadedModules


class AuditProvider(Provider):
    scope = Scope.REQUEST

    repository = provide(SqlAuditRepository, provides=AuditRepository)
    standalone = provide(SqlStandaloneAuditWriter, provides=StandaloneAuditWriter, scope=Scope.APP)
    uow = provide(SqlUnitOfWork, provides=UnitOfWork)
    policy_store = provide(SqlPolicyStore, provides=PolicyStore)
    views = provide(SqlViewRepository, provides=ViewRepository)
    exports_repository = provide(SqlExportRepository, provides=ExportRepository)
    archives_repository = provide(SqlArchiveRepository, provides=ArchiveRepository)
    sinks_repository = provide(SqlSinkRepository, provides=SinkRepository)
    ingest_cursors = provide(SqlIngestCursorRepository, provides=IngestCursorRepository)
    stores = provide(S3ObjectStores, provides=ObjectStores, scope=Scope.APP)
    transport = provide(SinkTransports, provides=SinkTransport, scope=Scope.APP)
    delivery_lock = provide(SqlDeliveryLock, provides=DeliveryLock, scope=Scope.APP)

    record = provide(RecordEvent)
    audit_log = provide(AuditLogImpl, provides=AuditLog)
    reader = provide(AuditReaderImpl, provides=AuditReader)
    cursors_facade = provide(IngestCursorsImpl, provides=IngestCursors)
    admin = provide(AuditAdminImpl, provides=AuditAdmin)
    list_events = provide(ListEvents)
    get_event = provide(GetEvent)
    list_actors = provide(ListActors)
    saved_views = provide(SavedViews)
    archives = provide(Archives)
    verify = provide(VerifyChain)
    sinks = provide(SinkService)
    maintain = provide(MaintainPartitions)

    @provide(scope=Scope.APP)
    def vocabulary(self, modules: LoadedModules) -> AuditVocabulary:
        return AuditVocabulary(decl for module in modules.enabled for decl in module.audit_actions())

    @provide(scope=Scope.APP)
    def maintenance(self, engine: AsyncEngine) -> PartitionMaintenance:
        return SqlPartitionMaintenance(engine)

    @provide(scope=Scope.APP)
    async def http(self) -> AsyncIterator[AuditHttp]:
        http = AuditHttp()
        yield http
        await http.aclose()

    @provide(scope=Scope.APP)
    def jobs(self, app: procrastinate.App, queue: JobQueue) -> Jobs:
        return ProcrastinateJobs(app, queue)

    @provide(scope=Scope.APP)
    def policy_cache(self, sessionmaker: async_sessionmaker[AsyncSession], settings: AuditSettings) -> PolicyCache:
        async def load() -> Policy:
            async with sessionmaker() as session:
                return policy_from(await SqlPolicyStore(session).load(), settings.retention_days)

        return PolicyCache(load)

    @provide(scope=Scope.APP)
    def stream_trigger(
        self, jobs: Jobs, sessionmaker: async_sessionmaker[AsyncSession], settings: AuditSettings
    ) -> StreamTrigger:
        async def has_sinks() -> bool:
            async with sessionmaker() as session:
                return await any_enabled_sink(session)

        return StreamTrigger(
            jobs,
            has_sinks,
            enabled=settings.deliver_on_record,
            delay_seconds=math.ceil(settings.settle_seconds) + 1,
        )

    @provide
    def policies(
        self,
        store: PolicyStore,
        uow: UnitOfWork,
        box: SecretBox,
        cache: PolicyCache,
        stores: ObjectStores,
        settings: AuditSettings,
    ) -> PolicyService:
        return PolicyService(store, uow, box, cache, stores, settings.retention_days)

    @provide
    def exports(
        self, events: AuditRepository, exports: ExportRepository, uow: UnitOfWork, jobs: Jobs, settings: AuditSettings
    ) -> Exports:
        return Exports(events, exports, uow, jobs, settings.export_sync_limit)

    @provide
    def deliver(
        self,
        sinks: SinkRepository,
        events: AuditRepository,
        transport: SinkTransport,
        lock: DeliveryLock,
        uow: UnitOfWork,
        domain_events: DomainEvents,
        settings: AuditSettings,
    ) -> DeliverSinks:
        return DeliverSinks(
            sinks,
            events,
            transport,
            lock,
            uow,
            domain_events,
            settle_seconds=settings.settle_seconds,
            batch_size=settings.delivery_batch,
        )
