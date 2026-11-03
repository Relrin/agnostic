"""Dependency wiring of the scheduler module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_scheduler.application.calls import SchedulerCalls
from agnostic_scheduler.application.ports import NoteStore
from agnostic_scheduler.application.schedules import Schedules
from agnostic_scheduler.application.watch import WatchScheduleFailures
from agnostic_scheduler.infrastructure.repository import SqlNoteStore


class SchedulerProvider(Provider):
    scope = Scope.REQUEST

    calls = provide(SchedulerCalls)
    schedules = provide(Schedules)
    watch = provide(WatchScheduleFailures)

    @provide
    def notes(self, session: AsyncSession) -> NoteStore:
        return SqlNoteStore(session)
