"""Module declaration: the audit log."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_audit import jobs
from agnostic_audit.api.router import router
from agnostic_audit.infrastructure.tables import AuditBase
from agnostic_audit.providers import AuditProvider
from agnostic_audit.settings import AuditSettings
from agnostic_kernel.modules import BaseModule, JobSpec, RouterSpec, ScopeDecl


class AuditModule(BaseModule):
    name = "audit"
    version = "0.1.0"
    depends_on = ()

    def settings_model(self) -> type[BaseSettings] | None:
        return AuditSettings

    def provide(self) -> Iterable[Provider]:
        return (AuditProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/audit", tags=("audit",)),)

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
        return (
            JobSpec(
                name=jobs.MAINTENANCE_TASK,
                func=jobs.maintain_partitions,
                queue="audit",
                periodic=AuditSettings().maintenance_cron,
            ),
        )
