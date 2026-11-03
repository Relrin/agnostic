"""Dependency wiring of the notifications module."""

from __future__ import annotations

from collections.abc import AsyncIterator

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_identity.facade import IdentityFacade
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus
from agnostic_kernel.jobs import JobQueue
from agnostic_kernel.mail import Mailer
from agnostic_kernel.settings import Settings
from agnostic_notifications.application.announcements import Announcements
from agnostic_notifications.application.deliver import Deliver
from agnostic_notifications.application.manage import Channels, Inbox, Preferences
from agnostic_notifications.application.notify import Notify
from agnostic_notifications.application.ports import OutboundHttp, Repositories
from agnostic_notifications.application.stream import EventStream
from agnostic_notifications.facade import Notifier, NotifierImpl
from agnostic_notifications.infrastructure.outbound import HttpOutbound
from agnostic_notifications.infrastructure.repository import SqlRepositories
from agnostic_notifications.settings import NotificationsSettings


class NotificationsProvider(Provider):
    scope = Scope.REQUEST

    stream = provide(EventStream)
    inbox = provide(Inbox)
    preferences = provide(Preferences)
    channels = provide(Channels)
    announcements = provide(Announcements)
    notifier = provide(NotifierImpl, provides=Notifier)

    @provide
    def repositories(self, session: AsyncSession, secrets: SecretBox) -> Repositories:
        return SqlRepositories(session, secrets)

    @provide(scope=Scope.APP)
    async def outbound(self, settings: NotificationsSettings) -> AsyncIterator[OutboundHttp]:
        client = HttpOutbound(settings.http_timeout_seconds)
        yield client
        await client.aclose()

    @provide
    def notify(
        self,
        repositories: Repositories,
        identity: IdentityFacade,
        queue: JobQueue,
        bus: EventBus,
        store: EphemeralStore,
        settings: Settings,
    ) -> Notify:
        return Notify(repositories, identity, queue, bus, store, settings.public_url())

    @provide
    def deliver(
        self, repositories: Repositories, mailer: Mailer, http: OutboundHttp, settings: NotificationsSettings
    ) -> Deliver:
        return Deliver(repositories, mailer, http, settings.slack_api_base)
