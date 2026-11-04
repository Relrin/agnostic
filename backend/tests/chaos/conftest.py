"""Chaos fixtures: PostgreSQL and Redis containers of their own that a test may pause, stop and start again.

The shared ``postgres_url`` / ``redis_url`` fixtures serve the other tests, so chaos never breaks them. Each container
here publishes a fixed host port, so a stopped and restarted server comes back at the same address the running app
already holds, as a restarted or failed-over primary behind a stable DNS name would. Docker is required.

Chaos tests run only when selected (``pytest -m chaos``): a plain ``pytest`` or ``-m "not integration"`` skips them.
"""

import asyncio
import os
import socket
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
import redis.asyncio as redis_asyncio

from tests.conftest import POSTGRES_IMAGE, REDIS_IMAGE


@pytest.fixture(autouse=True)
def _only_when_selected(request: pytest.FixtureRequest) -> None:
    if "chaos" not in str(request.config.getoption("markexpr") or ""):
        pytest.skip("chaos tests run with -m chaos (they start, pause and stop their own containers)")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class Chaos:
    """One container under test: break it and bring it back."""

    container: Any
    url: str

    @property
    def _docker(self) -> Any:
        return self.container.get_wrapped_container()

    def pause(self) -> None:
        self._docker.pause()

    def unpause(self) -> None:
        self._docker.unpause()

    def stop(self) -> None:
        self._docker.stop(timeout=1)

    def kill(self) -> None:
        self._docker.kill()

    def start(self) -> None:
        self._docker.start()


async def wait_until(probe: Any, *, timeout: float = 60.0) -> None:  # noqa: ASYNC109
    """Retry ``probe()`` until it stops raising."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            await probe()
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(0.25)
        else:
            return


async def postgres_ready(url: str) -> None:
    async def probe() -> None:
        connection = await asyncpg.connect(url, timeout=2)
        await connection.close()

    await wait_until(probe)


async def redis_ready(url: str) -> None:
    async def probe() -> None:
        client = redis_asyncio.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)  # pyright: ignore[reportUnknownMemberType]
        try:
            await client.ping()  # pyright: ignore[reportUnknownMemberType]
        finally:
            await client.aclose()

    await wait_until(probe)


@pytest.fixture
def chaos_postgres() -> Iterator[Chaos]:
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    port = free_port()
    container = PostgresContainer(POSTGRES_IMAGE, driver=None).with_bind_ports(5432, port)
    with container:
        url = f"postgresql://{container.username}:{container.password}@127.0.0.1:{port}/{container.dbname}"
        yield Chaos(container, url)


@pytest.fixture
def chaos_redis() -> Iterator[Chaos]:
    from testcontainers.community.redis import RedisContainer  # noqa: PLC0415

    port = free_port()
    container = RedisContainer(os.environ.get("AGNOSTIC_TEST_REDIS_IMAGE", REDIS_IMAGE)).with_bind_ports(6379, port)
    with container:
        yield Chaos(container, f"redis://127.0.0.1:{port}/0")


@pytest.fixture
async def postgres_up(chaos_postgres: Chaos) -> Chaos:
    await postgres_ready(chaos_postgres.url)
    return chaos_postgres


@pytest.fixture
async def redis_up(chaos_redis: Chaos) -> Chaos:
    await redis_ready(chaos_redis.url)
    return chaos_redis
