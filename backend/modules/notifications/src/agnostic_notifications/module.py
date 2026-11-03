"""Module declaration: realtime events for browsers, the inbox, and Slack/email/webhook notifications."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, EventHandlerSpec, JobSpec, RouterSpec, ScopeDecl
from agnostic_notifications import jobs
from agnostic_notifications.api.router import me_router, router
from agnostic_notifications.infrastructure.tables import NotificationsBase
from agnostic_notifications.providers import NotificationsProvider
from agnostic_notifications.settings import NotificationsSettings


class NotificationsModule(BaseModule):
    name = "notifications"
    version = "0.2.0"
    depends_on = ("access", "audit", "identity", "instances", "org")

    def settings_model(self) -> type[BaseSettings] | None:
        return NotificationsSettings

    def provide(self) -> Iterable[Provider]:
        return (NotificationsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, tags=("notifications",)),
            RouterSpec(router=me_router, prefix="/me", tags=("notifications",)),
        )

    def metadata(self) -> MetaData | None:
        return NotificationsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (ScopeDecl("notifications:write", "Manage org notification channels and default preferences"),)

    def jobs(self) -> Iterable[JobSpec]:
        retries = NotificationsSettings().delivery_retries
        return (JobSpec(name=jobs.DELIVER_TASK, func=jobs.deliver, queue="notifications", retry=retries),)

    def event_handlers(self) -> Iterable[EventHandlerSpec]:
        return (
            EventHandlerSpec("access.privileged_grant", jobs.on_privileged_grant),
            EventHandlerSpec("evals.regression", jobs.on_eval_regression),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("notifications.channel.created", "{actor} added the {kind} notification channel {channel}"),
            AuditActionDecl("notifications.channel.updated", "{actor} changed the notification channel {channel}"),
            AuditActionDecl("notifications.channel.deleted", "{actor} removed the notification channel {channel}"),
            AuditActionDecl("notifications.defaults.updated", "{actor} changed notification defaults ({events})"),
        )
