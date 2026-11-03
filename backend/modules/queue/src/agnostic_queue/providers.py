"""Dependency wiring of the queue module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_queue.application.operate import Queue


class QueueProvider(Provider):
    scope = Scope.REQUEST

    queue = provide(Queue)
