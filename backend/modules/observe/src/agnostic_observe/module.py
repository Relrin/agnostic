"""Module declaration: the Home overview, traces (comparison, span statistics), metrics and price tables."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec
from agnostic_kernel.tools import ToolSpec
from agnostic_observe import jobs
from agnostic_observe.api.router import org_router, router
from agnostic_observe.api.tools import TOOLS
from agnostic_observe.infrastructure.tables import ObserveBase
from agnostic_observe.providers import ObserveProvider
from agnostic_observe.settings import ObserveSettings


class ObserveModule(BaseModule):
    name = "observe"
    version = "0.3.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def settings_model(self) -> type[BaseSettings] | None:
        return ObserveSettings

    def provide(self) -> Iterable[Provider]:
        return (ObserveProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("observe",)),
            RouterSpec(router=org_router, tags=("observe",)),
        )

    def metadata(self) -> MetaData | None:
        return ObserveBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        cron = ObserveSettings().warm_cron
        return (JobSpec(name=jobs.WARM_TASK, func=jobs.warm_overviews, queue="default", periodic=cron or None),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (AuditActionDecl("observe.price_table.updated", "{actor} updated the price table of {where}"),)

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
