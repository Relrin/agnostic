"""Module declaration: the approvals inbox, routing and expiry, inline decisions and the pending-count feed."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_approvals import jobs
from agnostic_approvals.api.router import org_router, router
from agnostic_approvals.application.poller import run_poller, stop
from agnostic_approvals.infrastructure.tables import ApprovalsBase
from agnostic_approvals.providers import ApprovalsProvider
from agnostic_approvals.settings import ApprovalsSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, CapabilityProbe, JobSpec, RouterSpec


class ApprovalsModule(BaseModule):
    name = "approvals"
    version = "0.2.0"
    depends_on = ("access", "audit", "directory", "identity", "instances", "gateway", "notifications", "settings")

    def __init__(self) -> None:
        self._poller: asyncio.Task[None] | None = None

    def settings_model(self) -> type[BaseSettings] | None:
        return ApprovalsSettings

    def provide(self) -> Iterable[Provider]:
        return (ApprovalsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("approvals",)),
            RouterSpec(router=org_router, tags=("approvals",)),
        )

    def metadata(self) -> MetaData | None:
        return ApprovalsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        cron = ApprovalsSettings().watch_cron
        return (JobSpec(name=jobs.WATCH_TASK, func=jobs.watch, periodic=cron),) if cron else ()

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("approvals.decided", "{actor} {verb} {tool} on {component}"),
            AuditActionDecl("approvals.expired", "{tool} on {instance} expired without a decision"),
            AuditActionDecl("approvals.route.created", "{actor} routed approvals of {tool} on {where} to {route}"),
            AuditActionDecl("approvals.route.updated", "{actor} changed the approval route {route} on {where}"),
            AuditActionDecl("approvals.route.deleted", "{actor} removed the approval route {route} on {where}"),
            AuditActionDecl("approvals.policy.updated", "{actor} set approval expiry on {instance} to {state}"),
        )

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe("approvals", "Approvals for @approval tools and HumanReview steps"),)

    async def on_startup(self, container: AsyncContainer) -> None:
        settings = await container.get(ApprovalsSettings)
        if settings.poll_seconds > 0:
            self._poller = asyncio.create_task(run_poller(container, settings.poll_seconds), name="approvals-poller")

    async def on_shutdown(self, container: AsyncContainer) -> None:  # noqa: ARG002
        await stop(self._poller)
        self._poller = None
