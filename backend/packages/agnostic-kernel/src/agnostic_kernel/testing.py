"""Helpers for tests of the kernel and of modules."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agnostic_kernel.settings import Settings

UNREACHABLE_REDIS = "redis://127.0.0.1:1/0"
"""A Redis URL that refuses connections at once; for tests that must prove Redis is optional."""


def sqlite_url(directory: Path, name: str = "agnostic.db") -> str:
    return f"sqlite:///{(directory / name).as_posix()}"


def make_settings(database_url: str, redis_url: str = UNREACHABLE_REDIS, **overrides: Any) -> Settings:  # noqa: ANN401
    """Settings for tests: console logs, no ``.env`` file, explicit endpoints."""
    values: dict[str, Any] = {
        "env": "test",
        "database": {"url": database_url, "connect_timeout": 5},
        "redis": {"url": redis_url, "socket_timeout": 1},
        "log": {"level": "WARNING", "format": "console"},
        **overrides,
    }
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


async def wait_for[T](
    probe: Callable[[], Awaitable[T]],
    until: Callable[[T], bool],
    *,
    timeout: float = 10.0,  # noqa: ASYNC109  (a polling helper, not a cancellable operation)
    interval: float = 0.05,
) -> T:
    """Poll ``probe`` until ``until(result)`` holds; raise ``TimeoutError`` otherwise."""
    async with asyncio.timeout(timeout):
        while True:
            result = await probe()
            if until(result):
                return result
            await asyncio.sleep(interval)
