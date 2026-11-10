"""Module declaration: access (scopes, roles, bindings, authorization)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData
from sqlalchemy.exc import SQLAlchemyError

from agnostic_access import jobs
from agnostic_access.api.router import me_router, router
from agnostic_access.api.tools import TOOLS
from agnostic_access.application.use_cases import SyncCatalog
from agnostic_access.infrastructure.tables import AccessBase
from agnostic_access.providers import AccessProvider
from agnostic_access.settings import AccessSettings
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec
from agnostic_kernel.tools import ToolSpec

log = get_logger(__name__)


class AccessModule(BaseModule):
    name = "access"
    version = "0.4.1"
    depends_on = ("identity", "org", "instances", "settings", "audit", "directory")

    def settings_model(self) -> type[BaseSettings] | None:
        return AccessSettings

    def provide(self) -> Iterable[Provider]:
        return (AccessProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/access", tags=("access",)),
            RouterSpec(router=me_router, prefix="/me", tags=("me",)),
        )

    def metadata(self) -> MetaData | None:
        return AccessBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        cron = AccessSettings().expiry_cron
        return (JobSpec(name=jobs.EXPIRE_TASK, func=jobs.expire_bindings, periodic=cron),) if cron else ()

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("bindings.create", "{actor} gave {person} {grant} on {where}"),
            AuditActionDecl("bindings.delete", "{actor} removed {grant} on {where} from {person}"),
            AuditActionDecl("bindings.expire", "{grant} on {where} expired for {person}"),
            AuditActionDecl("roles.create", "{actor} created the role {role}"),
            AuditActionDecl("roles.update", "{actor} changed the role {role}: {change}"),
            AuditActionDecl("roles.delete", "{actor} deleted the role {role}"),
            AuditActionDecl("access.requests.create", "{actor} asked for {grant} on {where} for {hours} h"),
            AuditActionDecl("access.requests.approve", "{actor} approved {grant} on {where} for {person} ({hours} h)"),
            AuditActionDecl("access.requests.deny", "{actor} denied {person} {grant} on {where}"),
            AuditActionDecl("access.requests.cancel", "{actor} withdrew the request for {grant} on {where}"),
        )

    async def on_startup(self, container: AsyncContainer) -> None:
        # The catalog tables are a read model of code (built-in roles, scopes); a stale database only delays them.
        try:
            async with container() as request:
                await (await request.get(SyncCatalog))()
        except SQLAlchemyError as exc:
            log.warning("access.catalog_sync_skipped", reason="database not migrated?", error=str(exc)[:200])

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
