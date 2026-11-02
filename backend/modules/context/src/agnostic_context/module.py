"""Module declaration: memory, knowledge, learnings and file-system helpers over the AgentOS context routes."""

from __future__ import annotations

from collections.abc import Iterable

from dishka import Provider
from pydantic_settings import BaseSettings

from agnostic_context.api.router import org_router, router
from agnostic_context.providers import ContextProvider
from agnostic_context.settings import ContextSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec


class ContextModule(BaseModule):
    name = "context"
    version = "0.1.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def settings_model(self) -> type[BaseSettings] | None:
        return ContextSettings

    def provide(self) -> Iterable[Provider]:
        return (ContextProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("context",)),
            RouterSpec(router=org_router, tags=("context",)),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl(
                "context.memories.optimized",
                "{actor} optimized the memories of {user} on {where}: {before} → {after} ({tokens_saved} tokens saved)",
            ),
            AuditActionDecl(
                "context.learnings.user_deleted", "{actor} deleted {count} learnings ({types}) of {user} on {where}"
            ),
            AuditActionDecl(
                "context.data_subject.requested",
                "{actor} deleted the learnings of {user}: {deleted} instances done, {skipped} skipped, {failed} failed",
            ),
        )
