"""Shared fixtures.

Unit tests run on SQLite and need nothing else. Integration tests (``-m integration``) need PostgreSQL and Redis:
either set ``AGNOSTIC_TEST_DATABASE_URL`` / ``AGNOSTIC_TEST_REDIS_URL`` (e.g. the dev compose services), or let
testcontainers start them (Docker required). ``AGNOSTIC_TEST_REDIS_IMAGE`` swaps in Valkey or Dragonfly.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from agnostic_kernel.testing import sqlite_url
from agnostic_server.loops import new_event_loop

POSTGRES_IMAGE = (
    "pgvector/pgvector:0.8.7-pg18-trixie@sha256:5895949dfcdf308eb0cd31c950c93c14895c77f33fbedfecf1fa511ab1d4bcd2"
)
REDIS_IMAGE = "redis:8.10.3-alpine@sha256:21090af93f8324db2f0f0f4f38a7c60369d47d917e000c3423d89d2ae2883537"


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    # psycopg (Procrastinate) needs a selector loop on Windows; same factory as the real entry points.
    return {"agnostic": new_event_loop}


@pytest.fixture
def sqlite_database(tmp_path: Path) -> str:
    return sqlite_url(tmp_path)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    if url := os.environ.get("AGNOSTIC_TEST_DATABASE_URL"):
        yield url
        return
    from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    if url := os.environ.get("AGNOSTIC_TEST_REDIS_URL"):
        yield url
        return
    from testcontainers.community.redis import RedisContainer  # noqa: PLC0415

    with RedisContainer(os.environ.get("AGNOSTIC_TEST_REDIS_IMAGE", REDIS_IMAGE)) as container:
        yield f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"


@pytest.fixture
async def fresh_postgres(postgres_url: str) -> AsyncIterator[str]:
    """A brand-new, empty database on the test server, dropped afterwards."""
    base = make_url(postgres_url)
    name = f"agnostic_test_{uuid.uuid4().hex[:12]}"
    admin_dsn = base.set(drivername="postgresql").render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    yield base.set(database=name).render_as_string(hide_password=False)
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()
