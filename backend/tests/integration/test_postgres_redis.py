"""PostgreSQL + Redis: migrations, the Procrastinate worker, job progress, cache compatibility."""

import asyncio
import contextlib
from typing import Any

import httpx
import orjson
import procrastinate
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import text

from agnostic_kernel import migrations_runner
from agnostic_kernel.cache import create_redis, detect_server, probe_commands
from agnostic_kernel.checks import run_endpoint_checks
from agnostic_kernel.container import build_container
from agnostic_kernel.db import create_engine
from agnostic_kernel.jobs import JobProgressReporter, worker_options
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_kernel.testing import make_settings, wait_for
from agnostic_server.app import create_app
from tests.support.probe import with_probe

pytestmark = pytest.mark.integration


@pytest.fixture
async def settings(fresh_postgres: str, redis_url: str) -> Settings:
    settings = make_settings(fresh_postgres, redis_url)
    engine = create_engine(settings.database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    await engine.dispose()
    return settings


async def test_migrations_up_down_up(fresh_postgres: str) -> None:
    engine = create_engine(make_settings(fresh_postgres).database)
    modules = list(load_modules().installed.values())
    try:
        await migrations_runner.upgrade(engine, modules)
        async with engine.connect() as connection:
            tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                            "WHERE table_schema IN ('agnostic', 'procrastinate')"
                        )
                    )
                ).scalars()
            )
            extensions = set((await connection.execute(text("SELECT extname FROM pg_extension"))).scalars())
        assert {
            "agnostic.kernel_job_progress",
            "agnostic.identity_users",
            "agnostic.audit_events",
            "procrastinate.procrastinate_jobs",
        } <= tables
        assert {"citext", "pg_trgm"} <= extensions
        assert (await migrations_runner.state(engine, modules)).up_to_date

        await migrations_runner.downgrade(engine, modules, "base")
        assert (await migrations_runner.state(engine, modules)).current == ()
        await migrations_runner.upgrade(engine, modules)
        assert (await migrations_runner.state(engine, modules)).up_to_date
    finally:
        await engine.dispose()


async def test_endpoint_checks_pass(settings: Settings) -> None:
    results = await run_endpoint_checks(settings, list(load_modules().installed.values()))
    assert all(result.ok for result in results), results


async def test_cache_server_and_command_subset(redis_url: str) -> None:
    redis = create_redis(make_settings("sqlite://", redis_url).redis)
    try:
        server = await detect_server(redis)
        probe = await probe_commands(redis)
    finally:
        await redis.aclose()
    assert server.kind in {"redis", "valkey", "dragonfly"}
    assert probe.failed == {}


async def test_job_progress_is_stored_and_published(settings: Settings) -> None:
    container = build_container(settings, load_modules())
    try:
        reporter = await container.get(JobProgressReporter)
        redis = create_redis(settings.redis)
        pubsub = redis.pubsub()  # pyright: ignore[reportUnknownMemberType]
        await pubsub.subscribe("evt:job:42")  # pyright: ignore[reportUnknownMemberType]
        await reporter.report(42, "test.kind", 0.5, message="half")
        await reporter.report(42, "test.kind", 2.0, message="done", result={"n": 1})

        messages: list[dict[str, Any]] = []
        async with asyncio.timeout(5):
            while len(messages) < 2:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)  # pyright: ignore[reportUnknownMemberType]
                if message:
                    data = message["data"]
                    assert isinstance(data, bytes)
                    messages.append(orjson.loads(data))
        await pubsub.aclose()  # pyright: ignore[reportUnknownMemberType]
        await redis.aclose()
        assert [m["progress"] for m in messages] == [0.5, 1.0]

        engine = create_engine(settings.database)
        async with engine.connect() as connection:
            row = (
                await connection.execute(text("SELECT progress, message, result FROM agnostic.kernel_job_progress"))
            ).one()
        await engine.dispose()
        assert tuple(row) == (1.0, "done", {"n": 1})
    finally:
        await container.close()


async def test_api_and_worker_on_postgres(settings: Settings) -> None:
    modules = with_probe()
    app = create_app(settings, modules=modules)
    worker_container = build_container(settings, modules)
    jobs_app = await worker_container.get(procrastinate.App)
    worker = asyncio.create_task(
        jobs_app.run_worker_async(
            **worker_options(worker_container, queues=None, concurrency=2, install_signal_handlers=False)
        )
    )
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                ready = await http.get("/readyz")
                assert ready.status_code == 200, ready.text

                started = (await http.post("/api/v1/probe/jobs", json={"value": "from postgres"})).json()

                async def fetch() -> httpx.Response:
                    return await http.get(f"/api/v1/probe/jobs/{started['job_id']}")

                done = await wait_for(fetch, lambda response: response.status_code == 200, timeout=20)
                assert done.json()["result"] == {"echo": "from postgres"}
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await worker_container.close()
