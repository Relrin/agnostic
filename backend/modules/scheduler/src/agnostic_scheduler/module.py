"""Module declaration: schedules over AgentOS ``/schedules``, cron previews, failure notifications."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, CapabilityProbe, JobSpec, RouterSpec
from agnostic_kernel.tools import ToolSpec
from agnostic_scheduler import jobs
from agnostic_scheduler.api.router import router
from agnostic_scheduler.api.tools import TOOLS
from agnostic_scheduler.infrastructure.tables import SchedulerBase
from agnostic_scheduler.providers import SchedulerProvider
from agnostic_scheduler.settings import SchedulerSettings


class SchedulerModule(BaseModule):
    name = "scheduler"
    version = "0.4.1"
    depends_on = ("access", "audit", "identity", "instances", "gateway", "notifications")

    def settings_model(self) -> type[BaseSettings] | None:
        return SchedulerSettings

    def provide(self) -> Iterable[Provider]:
        return (SchedulerProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/instances", tags=("scheduler",)),)

    def metadata(self) -> MetaData | None:
        return SchedulerBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        cron = SchedulerSettings().watch_cron
        return (JobSpec(name=jobs.WATCH_TASK, func=jobs.watch_failures, periodic=cron),) if cron else ()

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("schedules.create", "{actor} created the schedule {schedule} ({target}) on {instance}"),
            AuditActionDecl("schedules.update", "{actor} changed the schedule {schedule} on {instance}"),
            AuditActionDecl("schedules.delete", "{actor} deleted the schedule {schedule} on {instance}"),
            AuditActionDecl("schedules.enable", "{actor} enabled the schedule {schedule} on {instance}"),
            AuditActionDecl("schedules.disable", "{actor} disabled the schedule {schedule} on {instance}"),
            AuditActionDecl("schedules.trigger", "{actor} triggered the schedule {schedule} on {instance}"),
        )

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe("scheduler", "Cron schedules that call AgentOS endpoints"),)

    def assistant_tools(self) -> Iterable[ToolSpec]:
        return TOOLS
