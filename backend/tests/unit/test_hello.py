"""hello domain and use cases with in-memory fakes."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agnostic_hello.application.use_cases import ComposeReply, CreateGreeting, GetGreeting, ListGreetings
from agnostic_hello.domain.greeting import Greeting, GreetingStatus, InvalidGreetingError, compose_reply
from agnostic_hello.facade import HelloFacadeImpl
from agnostic_kernel.errors import NotFoundError, ValidationFailedError

NOW = datetime(2026, 10, 31, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, Greeting] = {}
        self.commits = 0

    async def add(self, message: str) -> Greeting:
        greeting = Greeting(f"hel_{len(self.items):026d}", message, GreetingStatus.PENDING, None, NOW, NOW)
        self.items[greeting.id] = greeting
        return greeting

    async def get(self, greeting_id: str) -> Greeting | None:
        return self.items.get(greeting_id)

    async def save(self, greeting: Greeting) -> None:
        self.items[greeting.id] = greeting

    async def list_page(self, limit: int, after_id: str | None) -> Sequence[Greeting]:
        ordered = sorted(self.items.values(), key=lambda g: g.id, reverse=True)
        if after_id:
            ordered = [g for g in ordered if g.id < after_id]
        return ordered[:limit]

    async def count(self) -> int:
        return len(self.items)

    async def commit(self) -> None:
        self.commits += 1


class FakeScheduler:
    def __init__(self) -> None:
        self.scheduled: list[str] = []

    async def schedule_reply(self, greeting_id: str) -> int:
        self.scheduled.append(greeting_id)
        return len(self.scheduled)


class FakeProgress:
    def __init__(self) -> None:
        self.reports: list[tuple[int, float, str]] = []

    async def report(self, job_id: int, progress: float, message: str) -> None:
        self.reports.append((job_id, progress, message))


def test_message_validation() -> None:
    assert Greeting.validate_message("  a \n b ") == "a b"
    with pytest.raises(InvalidGreetingError):
        Greeting.validate_message("   ")
    with pytest.raises(InvalidGreetingError):
        Greeting.validate_message("x" * 281)


def test_compose_reply() -> None:
    assert compose_reply("one two", "Hi") == "Hi! You said: “one two” (2 words)."


async def test_create_commits_then_schedules() -> None:
    repo, scheduler = FakeRepository(), FakeScheduler()
    greeting = await CreateGreeting(repo, scheduler)("hey")
    assert repo.commits == 1
    assert scheduler.scheduled == [greeting.id]
    with pytest.raises(ValidationFailedError):
        await CreateGreeting(repo, scheduler)(" ")


async def test_get_and_list() -> None:
    repo = FakeRepository()
    for n in range(3):
        await repo.add(f"m{n}")
    page = await ListGreetings(repo)(2, None)
    assert [g.message for g in page.items] == ["m2", "m1"]
    assert page.next_after_id == page.items[-1].id
    rest = await ListGreetings(repo)(2, page.next_after_id)
    assert [g.message for g in rest.items] == ["m0"]
    assert rest.next_after_id is None
    assert (await GetGreeting(repo)(page.items[0].id)).message == "m2"
    with pytest.raises(NotFoundError):
        await GetGreeting(repo)("hel_missing")
    assert await HelloFacadeImpl(repo).greeting_count() == 3


async def test_compose_reply_use_case() -> None:
    repo, progress = FakeRepository(), FakeProgress()
    greeting = await repo.add("hello")
    replied = await ComposeReply(repo, progress, "Hey")(greeting.id, job_id=7)
    assert replied is not None
    assert replied.status is GreetingStatus.REPLIED
    assert replied == replace(replied, reply="Hey! You said: “hello” (1 words).")
    assert [p for _, p, _ in progress.reports] == [0.1, 1.0]
    assert await ComposeReply(repo, progress, "Hey")("hel_gone", job_id=8) is None
