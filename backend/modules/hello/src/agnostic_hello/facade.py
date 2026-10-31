"""The only import surface other modules may use."""

from __future__ import annotations

from typing import Protocol

from agnostic_hello.application.ports import GreetingRepository


class HelloFacade(Protocol):
    async def greeting_count(self) -> int: ...


class HelloFacadeImpl:
    def __init__(self, repository: GreetingRepository) -> None:
        self._repository = repository

    async def greeting_count(self) -> int:
        return await self._repository.count()
