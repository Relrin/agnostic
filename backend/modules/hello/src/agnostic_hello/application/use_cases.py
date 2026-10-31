"""Use cases of the hello module."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_hello.application.ports import GreetingRepository, ProgressReporter, ReplyScheduler
from agnostic_hello.domain.greeting import Greeting, InvalidGreetingError, compose_reply
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError, ValidationFailedError


@dataclass(frozen=True, slots=True)
class GreetingPage:
    items: list[Greeting]
    next_after_id: str | None


class CreateGreeting:
    def __init__(self, repository: GreetingRepository, scheduler: ReplyScheduler) -> None:
        self._repository = repository
        self._scheduler = scheduler

    async def __call__(self, message: str) -> Greeting:
        try:
            cleaned = Greeting.validate_message(message)
        except InvalidGreetingError as exc:
            raise ValidationFailedError(str(exc)) from exc
        greeting = await self._repository.add(cleaned)
        await self._repository.commit()
        _ = await self._scheduler.schedule_reply(greeting.id)
        return greeting


class GetGreeting:
    def __init__(self, repository: GreetingRepository) -> None:
        self._repository = repository

    async def __call__(self, greeting_id: str) -> Greeting:
        greeting = await self._repository.get(greeting_id)
        if greeting is None:
            raise NotFoundError(f"Greeting {greeting_id} doesn't exist.")
        return greeting


class ListGreetings:
    def __init__(self, repository: GreetingRepository) -> None:
        self._repository = repository

    async def __call__(self, limit: int, after_id: str | None) -> GreetingPage:
        rows = list(await self._repository.list_page(limit + 1, after_id))
        has_more = len(rows) > limit
        items = rows[:limit]
        return GreetingPage(items=items, next_after_id=items[-1].id if has_more and items else None)


class ComposeReply:
    """Background step: write the reply for a greeting, reporting progress on the way."""

    def __init__(self, repository: GreetingRepository, progress: ProgressReporter, prefix: str) -> None:
        self._repository = repository
        self._progress = progress
        self._prefix = prefix

    async def __call__(self, greeting_id: str, job_id: int) -> Greeting | None:
        await self._progress.report(job_id, 0.1, "Reading the greeting")
        greeting = await self._repository.get(greeting_id)
        if greeting is None:
            await self._progress.report(job_id, 1.0, "Greeting was deleted; nothing to do")
            return None
        replied = greeting.with_reply(compose_reply(greeting.message, self._prefix), utcnow())
        await self._repository.save(replied)
        await self._repository.commit()
        await self._progress.report(job_id, 1.0, "Reply written")
        return replied
