"""Module declaration: everything the hello module contributes to the control plane."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_hello import jobs
from agnostic_hello.api.router import router
from agnostic_hello.infrastructure.jobs_adapter import COMPOSE_REPLY_TASK, HEARTBEAT_TASK
from agnostic_hello.infrastructure.tables import HelloBase
from agnostic_hello.providers import HelloProvider
from agnostic_hello.settings import HelloSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec, ScopeDecl


class HelloModule(BaseModule):
    name = "hello"
    version = "0.1.0"
    depends_on = ()

    def settings_model(self) -> type[BaseSettings] | None:
        return HelloSettings

    def provide(self) -> Iterable[Provider]:
        return (HelloProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/hello", tags=("hello",)),)

    def metadata(self) -> MetaData | None:
        return HelloBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("hello:read", "See greetings"),
            ScopeDecl("hello:write", "Create greetings"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        return (
            JobSpec(name=COMPOSE_REPLY_TASK, func=jobs.compose_reply, retry=3),
            JobSpec(name=HEARTBEAT_TASK, func=jobs.heartbeat, periodic=HelloSettings().heartbeat_cron),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (AuditActionDecl("hello.greeting.create", "{actor} created greeting {greeting_id}"),)
