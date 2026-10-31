"""Dependency wiring of the hello module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_hello.application.ports import GreetingRepository, ProgressReporter, ReplyScheduler
from agnostic_hello.application.use_cases import ComposeReply, CreateGreeting, GetGreeting, ListGreetings
from agnostic_hello.facade import HelloFacade, HelloFacadeImpl
from agnostic_hello.infrastructure.jobs_adapter import KernelProgressReporter, QueuedReplyScheduler
from agnostic_hello.infrastructure.repository import SqlGreetingRepository
from agnostic_hello.settings import HelloSettings


class HelloProvider(Provider):
    scope = Scope.REQUEST

    repository = provide(SqlGreetingRepository, provides=GreetingRepository)
    scheduler = provide(QueuedReplyScheduler, provides=ReplyScheduler, scope=Scope.APP)
    progress = provide(KernelProgressReporter, provides=ProgressReporter, scope=Scope.APP)
    facade = provide(HelloFacadeImpl, provides=HelloFacade)

    create_greeting = provide(CreateGreeting)
    get_greeting = provide(GetGreeting)
    list_greetings = provide(ListGreetings)

    @provide
    def compose_reply(
        self,
        repository: GreetingRepository,
        progress: ProgressReporter,
        settings: HelloSettings,
    ) -> ComposeReply:
        return ComposeReply(repository, progress, settings.reply_prefix)
