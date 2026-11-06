"""Module declaration: the System page (Owners and Administrators)."""

from __future__ import annotations

from collections.abc import Iterable

from dishka import Provider

from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec, ScopeDecl
from agnostic_system.api.router import router
from agnostic_system.providers import SystemProvider


class SystemModule(BaseModule):
    name = "system"
    version = "0.2.0"
    depends_on = ("audit", "instances")

    def provide(self) -> Iterable[Provider]:
        return (SystemProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/system", tags=("system",)),)

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("org:system:read", "See the System page: versions, endpoints, job queues and delivery backlogs"),
            ScopeDecl("org:system:manage", "Retry or discard failed background jobs"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("system.job.retry", "{actor} retried the failed job {task} #{job}"),
            AuditActionDecl("system.job.discard", "{actor} discarded the failed job {task} #{job}"),
        )
