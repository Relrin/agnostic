"""Module declaration: the gateway to AgentOS instances."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_gateway import jobs
from agnostic_gateway.api.router import policies_router, router
from agnostic_gateway.api.tools import TOOLS
from agnostic_gateway.infrastructure.upstream import GatewayBase
from agnostic_gateway.providers import GatewayProvider
from agnostic_gateway.settings import GatewaySettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec
from agnostic_kernel.tools import ToolSpec


class GatewayModule(BaseModule):
    name = "gateway"
    version = "0.2.0"
    depends_on = ("access", "instances", "settings", "audit")

    def settings_model(self) -> type[BaseSettings] | None:
        return GatewaySettings

    def provide(self) -> Iterable[Provider]:
        return (GatewayProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("gateway",)),
            RouterSpec(router=policies_router, prefix="/gateway", tags=("gateway",)),
        )

    def metadata(self) -> MetaData | None:
        return GatewayBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("gateway.request", "{actor} called {route} on {instance}"),
            AuditActionDecl("gateway.denied", "{actor} was denied {route} on {instance}: missing {scope}"),
            AuditActionDecl("gateway.elevated", "{actor} called {route} on {instance} as Instance admin ({scope})"),
            AuditActionDecl("gateway.direct_token", "{actor} got a direct-mode token for {instance}"),
            AuditActionDecl("agentos.access", "{actor} called {route} on {instance}"),
            AuditActionDecl("agentos.role.created", "{actor} created an AgentOS role on {instance}"),
            AuditActionDecl("agentos.role.updated", "{actor} changed an AgentOS role on {instance}"),
            AuditActionDecl("agentos.role.set_scopes", "{actor} changed an AgentOS role's scopes on {instance}"),
            AuditActionDecl("agentos.role.removed", "{actor} removed an AgentOS role on {instance}"),
            AuditActionDecl("agentos.user.assigned", "{actor} assigned an AgentOS role on {instance}"),
            AuditActionDecl("agentos.user.unassigned", "{actor} removed an AgentOS role assignment on {instance}"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        return (
            JobSpec(
                name=jobs.INGEST_TASK,
                func=jobs.ingest_authz,
                queue="gateway",
                periodic=GatewaySettings().ingest_cron,
            ),
        )

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
