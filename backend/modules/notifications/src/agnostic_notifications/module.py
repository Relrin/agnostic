"""Module declaration: realtime events for browsers."""

from __future__ import annotations

from collections.abc import Iterable

from dishka import Provider
from pydantic_settings import BaseSettings

from agnostic_kernel.modules import BaseModule, RouterSpec
from agnostic_notifications.api.router import router
from agnostic_notifications.providers import NotificationsProvider
from agnostic_notifications.settings import NotificationsSettings


class NotificationsModule(BaseModule):
    name = "notifications"
    version = "0.1.0"
    depends_on = ("access", "instances")

    def settings_model(self) -> type[BaseSettings] | None:
        return NotificationsSettings

    def provide(self) -> Iterable[Provider]:
        return (NotificationsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, tags=("notifications",)),)
