"""Dependency wiring of the audit module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_audit.application.ports import AuditRepository, PartitionMaintenance, StandaloneAuditWriter
from agnostic_audit.application.use_cases import AuditVocabulary, GetEvent, ListEvents, MaintainPartitions, RecordEvent
from agnostic_audit.facade import AuditLog, AuditLogImpl, AuditReader, AuditReaderImpl
from agnostic_audit.infrastructure.repository import (
    SqlAuditRepository,
    SqlPartitionMaintenance,
    SqlStandaloneAuditWriter,
)
from agnostic_audit.settings import AuditSettings
from agnostic_kernel.modules import LoadedModules


class AuditProvider(Provider):
    scope = Scope.REQUEST

    repository = provide(SqlAuditRepository, provides=AuditRepository)
    standalone = provide(SqlStandaloneAuditWriter, provides=StandaloneAuditWriter, scope=Scope.APP)
    record = provide(RecordEvent)
    audit_log = provide(AuditLogImpl, provides=AuditLog)
    reader = provide(AuditReaderImpl, provides=AuditReader)
    list_events = provide(ListEvents)
    get_event = provide(GetEvent)

    @provide(scope=Scope.APP)
    def vocabulary(self, modules: LoadedModules) -> AuditVocabulary:
        return AuditVocabulary(decl for module in modules.enabled for decl in module.audit_actions())

    @provide(scope=Scope.APP)
    def maintenance(self, engine: AsyncEngine) -> PartitionMaintenance:
        return SqlPartitionMaintenance(engine)

    @provide(scope=Scope.APP)
    def maintain(self, maintenance: PartitionMaintenance, settings: AuditSettings) -> MaintainPartitions:
        return MaintainPartitions(maintenance, settings.retention_days)
