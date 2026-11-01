"""Module declaration: inline approval decisions and the pending-count feed."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings

from agnostic_approvals.api.router import router
from agnostic_approvals.application.poller import run_poller, stop
from agnostic_approvals.providers import ApprovalsProvider
from agnostic_approvals.settings import ApprovalsSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, CapabilityProbe, RouterSpec


class ApprovalsModule(BaseModule):
    name = "approvals"
    version = "0.1.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def __init__(self) -> None:
        self._poller: asyncio.Task[None] | None = None

    def settings_model(self) -> type[BaseSettings] | None:
        return ApprovalsSettings

    def provide(self) -> Iterable[Provider]:
        return (ApprovalsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/instances", tags=("approvals",)),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (AuditActionDecl("approvals.decided", "{actor} {verb} {tool} on {component}"),)

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe("approvals", "Approvals for @approval tools and HumanReview steps"),)

    async def on_startup(self, container: AsyncContainer) -> None:
        settings = await container.get(ApprovalsSettings)
        if settings.poll_seconds > 0:
            self._poller = asyncio.create_task(run_poller(container, settings.poll_seconds), name="approvals-poller")

    async def on_shutdown(self, container: AsyncContainer) -> None:  # noqa: ARG002
        await stop(self._poller)
        self._poller = None
