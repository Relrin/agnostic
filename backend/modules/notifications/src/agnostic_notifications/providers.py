"""Dependency wiring of the notifications module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_notifications.application.stream import EventStream


class NotificationsProvider(Provider):
    scope = Scope.REQUEST

    stream = provide(EventStream)
