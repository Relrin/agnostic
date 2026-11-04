"""Module declaration: the audit log."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_audit import jobs
from agnostic_audit.api.governance import router as governance_router
from agnostic_audit.api.router import router
from agnostic_audit.api.tools import TOOLS
from agnostic_audit.infrastructure.tables import AuditBase
from agnostic_audit.providers import AuditProvider
from agnostic_audit.settings import AuditSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec, ScopeDecl
from agnostic_kernel.tools import ToolSpec


class AuditModule(BaseModule):
    name = "audit"
    version = "0.1.0"
    depends_on = ()

    def settings_model(self) -> type[BaseSettings] | None:
        return AuditSettings

    def provide(self) -> Iterable[Provider]:
        return (AuditProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/audit", tags=("audit",)),
            RouterSpec(router=governance_router, prefix="/audit", tags=("audit",)),
        )

    def metadata(self) -> MetaData | None:
        return AuditBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("audit:read", "View the audit log"),
            ScopeDecl("audit:export", "Export the audit log"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        settings = AuditSettings()
        return (
            JobSpec(
                name=jobs.MAINTENANCE_TASK,
                func=jobs.maintain_partitions,
                queue="audit",
                periodic=settings.maintenance_cron,
            ),
            JobSpec(name=jobs.DELIVER_TASK, func=jobs.deliver_sinks, queue="audit", periodic=settings.deliver_cron),
            JobSpec(name=jobs.EXPORT_TASK, func=jobs.export_events, queue="audit"),
            JobSpec(name=jobs.RESTORE_TASK, func=jobs.restore_month, queue="audit"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("audit.export", "{actor} exported {count} audit events as {format}"),
            AuditActionDecl("audit.export.requested", "{actor} started a background export of audit events"),
            AuditActionDecl("audit.restore", "{actor} restored the archived audit events of {month}"),
            AuditActionDecl("audit.policy.update", "{actor} changed the audit retention and archive policy"),
            AuditActionDecl("audit.sinks.create", "{actor} added the SIEM sink {resource}"),
            AuditActionDecl("audit.sinks.update", "{actor} changed the SIEM sink {resource}"),
            AuditActionDecl("audit.sinks.delete", "{actor} removed the SIEM sink {resource}"),
            AuditActionDecl("audit.views.share", "{actor} changed the shared audit view {resource}"),
        )

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
