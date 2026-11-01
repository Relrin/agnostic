"""Module declaration: AgentOS instances."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_instances import jobs
from agnostic_instances.api.router import router, well_known
from agnostic_instances.domain.instances import CAPABILITIES
from agnostic_instances.infrastructure.tables import InstancesBase
from agnostic_instances.providers import InstancesProvider
from agnostic_instances.search import instance_documents
from agnostic_instances.settings import InstancesSettings
from agnostic_kernel.modules import (
    AuditActionDecl,
    BaseModule,
    CapabilityProbe,
    JobSpec,
    RouterSpec,
    ScopeDecl,
    SearchProvider,
)


class InstancesModule(BaseModule):
    name = "instances"
    version = "0.1.0"
    depends_on = ("audit",)

    def settings_model(self) -> type[BaseSettings] | None:
        return InstancesSettings

    def provide(self) -> Iterable[Provider]:
        return (InstancesProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("instances",)),
            RouterSpec(router=well_known, prefix="/.well-known/agnostic", tags=("jwks",), root=True),
        )

    def metadata(self) -> MetaData | None:
        return InstancesBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("os:read", "See connected instances, their health and capabilities"),
            ScopeDecl("os:write", "Connect and update instances"),
            ScopeDecl("os:delete", "Delete instance records"),
            ScopeDecl("os:keys:rotate", "Rotate an instance's JWT key pair"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        settings = InstancesSettings()
        return (
            JobSpec(name=jobs.HEALTH_TASK, func=jobs.check_health, queue="instances", periodic=settings.health_cron),
            JobSpec(
                name=jobs.SNAPSHOT_TASK, func=jobs.refresh_snapshots, queue="instances", periodic=settings.snapshot_cron
            ),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("instances.create", "{actor} connected {resource} ({endpoint})"),
            AuditActionDecl("instances.update", "{actor} changed {resource}: {keys}"),
            AuditActionDecl("instances.delete", "{actor} deleted the instance record {resource}"),
            AuditActionDecl("instances.test", "{actor} tested the connection to {resource}: {result}"),
            AuditActionDecl("instances.keys.stage", "{actor} staged a next key for {resource} ({kid})"),
            AuditActionDecl("instances.keys.activate", "{actor} activated key {kid} on {resource}"),
            AuditActionDecl("instances.keys.cancel", "{actor} cancelled the staged key {kid} on {resource}"),
        )

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe(name, description) for name, description in CAPABILITIES.items())

    def search_providers(self) -> Iterable[SearchProvider]:
        return (SearchProvider(entity="instance", documents=instance_documents),)
