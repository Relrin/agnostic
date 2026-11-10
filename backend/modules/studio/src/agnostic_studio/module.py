"""Module declaration: Studio on AgentOS components.

The registry catalog, the workflow builder, code that round-trips into configs, gated publish and promotion.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec, ScopeDecl
from agnostic_kernel.tools import ToolSpec
from agnostic_studio.api.router import org_router, router
from agnostic_studio.api.tools import TOOLS
from agnostic_studio.application.ports import SourceRunner
from agnostic_studio.infrastructure.isolation import SourceWorkers
from agnostic_studio.infrastructure.tables import StudioBase
from agnostic_studio.providers import StudioProvider
from agnostic_studio.settings import StudioSettings


class StudioModule(BaseModule):
    name = "studio"
    version = "0.4.1"
    depends_on = ("access", "audit", "instances", "gateway", "evals", "observe")

    def settings_model(self) -> type[BaseSettings] | None:
        return StudioSettings

    def provide(self) -> Iterable[Provider]:
        return (StudioProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("studio",)),
            RouterSpec(router=org_router, tags=("studio",)),
        )

    def metadata(self) -> MetaData | None:
        return StudioBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    async def on_shutdown(self, container: AsyncContainer) -> None:
        workers = await container.get(SourceRunner)
        if isinstance(workers, SourceWorkers):
            workers.close()

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("studio:promote", "Promote components between instances"),
            ScopeDecl("evals:gates:override", "Publish past a failed eval gate, with a reason"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("components.configs.create", "{actor} created {version} of {component} ({how})"),
            AuditActionDecl("components.set_current", "{actor} made {to} of {component} current instead of {from}"),
            AuditActionDecl("components.renamed", "{actor} renamed {component} from {from} to {to} on {instance}"),
            AuditActionDecl("components.archived", "{actor} archived {component} on {instance}"),
            AuditActionDecl("components.restored", "{actor} restored {component} on {instance}"),
            AuditActionDecl("studio.publish", "{actor} published {component} {version} on {instance}: {summary}"),
            AuditActionDecl("studio.promote", "{actor} promoted {component} from {from} to {to} ({outcome})"),
            AuditActionDecl(
                "evals.gate.override", "{actor} published {component} {version} past its eval gate: {reason}"
            ),
        )

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
