"""Module declaration: the tool catalog.

Approved MCP servers and Agno toolkits, set up once for the organization, for a team, or by a builder for one
component, and offered as tool blocks in Studio. Each runtime's bridge pulls the entries for its instance and
registers them; no secret leaves the control plane because credentials are environment variable names on the runtime.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec, ScopeDecl
from agnostic_tool_catalog import jobs
from agnostic_tool_catalog.api.router import router
from agnostic_tool_catalog.application.ports import LOCAL, NOTIFY_TASK, QUEUE, READ, SYNC, WRITE
from agnostic_tool_catalog.infrastructure.tables import ToolCatalogBase
from agnostic_tool_catalog.providers import ToolCatalogProvider


class ToolCatalogModule(BaseModule):
    name = "tool_catalog"
    version = "0.4.0"
    depends_on = ("access", "audit", "directory", "instances", "service_accounts", "studio")

    def provide(self) -> Iterable[Provider]:
        return (ToolCatalogProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/tool-catalog", tags=("tool_catalog",)),)

    def metadata(self) -> MetaData | None:
        return ToolCatalogBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl(READ, "See the tool catalog and use its entries in Studio"),
            ScopeDecl(WRITE, "Manage organization tool catalog entries, and every team's and builder's"),
            ScopeDecl(LOCAL, "Add tools that run commands on runtimes (stdio MCP servers, shell, python, files)"),
            ScopeDecl(SYNC, "Pull an instance's tool catalog (a runtime's bridge)"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        return (JobSpec(name=NOTIFY_TASK, func=jobs.notify, queue=QUEUE),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("tool_catalog.create", "{actor} added {entry} to the tool catalog ({level}, {name})"),
            AuditActionDecl("tool_catalog.update", "{actor} changed {entry} in the tool catalog ({level})"),
            AuditActionDecl("tool_catalog.delete", "{actor} removed {entry} from the tool catalog ({level})"),
            AuditActionDecl("tool_catalog.enable", "{actor} offered {entry} again ({level})"),
            AuditActionDecl("tool_catalog.disable", "{actor} stopped offering {entry} ({level})"),
            AuditActionDecl("tool_catalog.sync_token", "{actor} issued a tool catalog sync token for {instance}"),
            AuditActionDecl("tool_catalog.sync", "{actor} asked {instance} to pull the tool catalog ({outcome})"),
        )
