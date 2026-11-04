"""Dependency wiring of the system module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_system.application.status import SystemStatus


class SystemProvider(Provider):
    scope = Scope.REQUEST

    status = provide(SystemStatus)
