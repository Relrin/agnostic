"""Module declaration: access (scopes, roles, bindings, authorization)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import AsyncContainer, Provider
from sqlalchemy import MetaData
from sqlalchemy.exc import SQLAlchemyError

from agnostic_access.api.router import me_router, router
from agnostic_access.application.use_cases import SyncCatalog
from agnostic_access.infrastructure.tables import AccessBase
from agnostic_access.providers import AccessProvider
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec

log = get_logger(__name__)


class AccessModule(BaseModule):
    name = "access"
    version = "0.1.0"
    depends_on = ("identity", "org", "instances", "settings", "audit")

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

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("bindings.create", "{actor} gave {person} {grant} on {where}"),
            AuditActionDecl("bindings.delete", "{actor} removed {grant} on {where} from {person}"),
        )

    async def on_startup(self, container: AsyncContainer) -> None:
        # The catalog tables are a read model of code (built-in roles, scopes); a stale database only delays them.
        try:
            async with container() as request:
                await (await request.get(SyncCatalog))()
        except SQLAlchemyError as exc:
            log.warning("access.catalog_sync_skipped", reason="database not migrated?", error=str(exc)[:200])
