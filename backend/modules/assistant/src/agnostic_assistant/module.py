"""Module declaration: Ask your OS and the natural-language explainers.

An agno agent answers in the worker, as the person who asked: it may only call the read-only tools other modules
contribute, filtered by that person's scopes. The module is optional: disable it with
``AGNOSTIC_MODULES__DISABLED=assistant``. Without a configured model it calls nothing, and the web app shows no AI
features outside settings.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_assistant import jobs
from agnostic_assistant.api.router import org_router, router
from agnostic_assistant.application import tasks
from agnostic_assistant.application.tools import ToolCatalog
from agnostic_assistant.facade import AssistantStatusReader
from agnostic_assistant.infrastructure.tables import AssistantBase
from agnostic_assistant.providers import AssistantProvider
from agnostic_assistant.settings import AssistantSettings
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec, ScopeDecl, SealedColumn

log = get_logger(__name__)


class AssistantModule(BaseModule):
    name = "assistant"
    version = "0.3.0"
    depends_on = ("access", "audit", "identity", "instances", "gateway")

    def settings_model(self) -> type[BaseSettings] | None:
        return AssistantSettings

    def provide(self) -> Iterable[Provider]:
        return (AssistantProvider(),)

    def sealed_columns(self) -> Iterable[SealedColumn]:
        return (SealedColumn("asst_settings", "api_key_enc"),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("assistant",)),
            RouterSpec(router=org_router, tags=("assistant",)),
        )

    def metadata(self) -> MetaData | None:
        return AssistantBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (ScopeDecl("assistant:use", "Use Ask your OS and the AI explanations"),)

    def jobs(self) -> Iterable[JobSpec]:
        specs = [JobSpec(name=tasks.ANSWER_TASK, func=jobs.answer, queue=tasks.QUEUE)]
        if cron := AssistantSettings().prune_cron:
            specs.append(JobSpec(name=tasks.PRUNE_TASK, func=jobs.prune, queue=tasks.QUEUE, periodic=cron))
        return specs

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("assistant.ask", "{actor} asked Ask your OS ({tools})"),
            AuditActionDecl("assistant.explain", "{actor} generated a {kind} ({tools})"),
            AuditActionDecl("assistant.settings.update", "{actor} changed AI features (now {state}, model {model})"),
            AuditActionDecl("assistant.conversation.delete", "{actor} deleted the conversation {title}"),
        )

    async def features(self, container: AsyncContainer) -> Mapping[str, bool]:
        available = await (await container.get(AssistantStatusReader)).available()
        return {
            "assistant": available["assistant"],
            "assistant.summaries": available["summaries"],
            "assistant.suggestions": available["suggestions"],
        }

    async def on_startup(self, container: AsyncContainer) -> None:
        # agno reports usage to its makers unless told not to; an air-gapped install must make no unrequested calls.
        os.environ.setdefault("AGNO_TELEMETRY", "false")
        catalog = await container.get(ToolCatalog)
        log.info("assistant.tools", tools=[spec.name for spec in catalog.specs()])
