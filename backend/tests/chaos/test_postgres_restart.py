"""PostgreSQL restarts (a clean stop, a crash) or freezes: requests fail fast while it is gone, then the same process
serves again on its own: the pool drops dead connections, the worker reconnects and picks up new jobs."""

import asyncio
import contextlib
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
import procrastinate
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agnostic_kernel.container import build_container
from agnostic_kernel.jobs import JobQueue, keep_working, worker_options
from agnostic_kernel.tables import JobProgressRow
from tests.chaos.conftest import Chaos, postgres_ready
from tests.support.probe import ECHO_TASK, with_probe
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.chaos

NEVER = "0 0 1 1 *"
FAIL_FAST = 8.0
"""Connect timeout (5 s) plus slack: no request may hang on a database that is gone."""
RECOVERY = 30.0
RESETS_REACH_CLIENTS = sys.platform == "linux"
"""Docker Desktop's port proxy keeps client sockets open when the server dies, so there a restart looks like the frozen
case below (the pool's pre-ping waits on a silent socket). On Linux the server's FIN/RST reach the app."""


@dataclass(frozen=True)
class Outcome:
    status: int
    seconds: float


async def attempt(call: Callable[[], Awaitable[httpx.Response]], *, limit: float = 30.0) -> Outcome:
    """The status a client sees: an exception escaping the app is the 500 a server would answer."""
    started = time.monotonic()
    try:
        async with asyncio.timeout(limit):
            response = await call()
    except TimeoutError:
        return Outcome(0, time.monotonic() - started)
    except Exception:  # noqa: BLE001
        return Outcome(500, time.monotonic() - started)
    return Outcome(response.status_code, time.monotonic() - started)


async def recovered(call: Callable[[], Awaitable[httpx.Response]]) -> float:
    started = time.monotonic()
    while time.monotonic() - started < RECOVERY:
        if (await attempt(call, limit=10)).status == 200:
            return time.monotonic() - started
        await asyncio.sleep(0.5)
    pytest.fail(f"no 200 within {RECOVERY} s of the database coming back")


@pytest.fixture
async def stack(postgres_up: Chaos, redis_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(postgres_up.url, redis_url=redis_url) as running:
        yield running


@dataclass
class Worker:
    queue: JobQueue
    task: asyncio.Task[None]


@asynccontextmanager
async def running_worker(stack: Stack) -> AsyncGenerator[Worker]:
    """A worker of its own, with the probe's echo job, against the same database (as ``agnostic worker`` runs)."""
    container = build_container(stack.settings, with_probe())
    jobs_app = await container.get(procrastinate.App)
    task = asyncio.create_task(
        keep_working(jobs_app, worker_options(container, queues=None, concurrency=2, install_signal_handlers=False))
    )
    try:
        yield Worker(await container.get(JobQueue), task)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        await container.close()


async def restart_database(postgres: Chaos) -> None:
    postgres.stop()
    await asyncio.sleep(2)
    postgres.start()
    await postgres_ready(postgres.url)


async def wait_for_echo(stack: Stack, queue: JobQueue, value: str) -> None:
    job_id = await queue.defer(ECHO_TASK, value=value)
    sessionmaker = await stack.container.get(async_sessionmaker[AsyncSession])
    started = time.monotonic()
    while time.monotonic() - started < RECOVERY:
        async with sessionmaker() as session:
            row = await session.scalar(select(JobProgressRow).where(JobProgressRow.job_id == job_id))
        if row is not None and row.result == {"echo": value}:
            return
        await asyncio.sleep(0.25)
    pytest.fail(f"the worker didn't run job {job_id} within {RECOVERY} s")


@pytest.mark.parametrize("how", ["stop", "kill"])
async def test_requests_fail_fast_then_recover_without_a_restart(stack: Stack, postgres_up: Chaos, how: str) -> None:
    owner = await stack.owner()
    anonymous = stack.client()
    assert (await owner.get("/api/v1/instances")).status_code == 200

    postgres_up.stop() if how == "stop" else postgres_up.kill()
    outages = [await attempt(lambda: owner.get("/api/v1/instances")) for _ in range(3)]
    assert all(outcome.status >= 500 for outcome in outages), outages
    ready = await attempt(lambda: anonymous.get("/readyz"))
    assert ready.status == 503
    if RESETS_REACH_CLIENTS:
        assert all(outcome.seconds < FAIL_FAST for outcome in [*outages, ready]), [*outages, ready]

    postgres_up.start()
    await postgres_ready(postgres_up.url)
    assert await recovered(lambda: owner.get("/api/v1/instances")) < RECOVERY
    assert (await anonymous.get("/readyz")).status_code == 200


async def test_jobs_queued_across_the_restart_run_once_a_worker_is_up(stack: Stack, postgres_up: Chaos) -> None:
    async with running_worker(stack) as worker:
        await wait_for_echo(stack, worker.queue, "before")
    await restart_database(postgres_up)
    async with running_worker(stack) as worker:
        await wait_for_echo(stack, worker.queue, "after")


async def test_the_worker_survives_a_database_restart(stack: Stack, postgres_up: Chaos) -> None:
    async with running_worker(stack) as worker:
        await wait_for_echo(stack, worker.queue, "before")
        await restart_database(postgres_up)
        await asyncio.sleep(3)
        assert not worker.task.done(), "the worker stopped"
        await wait_for_echo(stack, worker.queue, "after")


async def test_requests_fail_fast_while_the_database_is_frozen(
    postgres_up: Chaos, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen primary answers nothing: the command timeout ends the wait and the request gets a 503."""
    monkeypatch.setenv("AGNOSTIC_DATABASE__COMMAND_TIMEOUT", "3")
    monkeypatch.setenv("AGNOSTIC_DATABASE__POOL_TIMEOUT", "3")
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(postgres_up.url, redis_url=redis_url) as stack:
        await _frozen_database_fails_fast(stack, postgres_up)


async def _frozen_database_fails_fast(stack: Stack, postgres_up: Chaos) -> None:
    owner = await stack.owner()
    assert (await owner.get("/api/v1/instances")).status_code == 200
    postgres_up.pause()
    try:
        frozen = await attempt(lambda: owner.get("/api/v1/instances"), limit=20)
    finally:
        postgres_up.unpause()
    assert frozen.status >= 500, frozen
    assert frozen.seconds < FAIL_FAST, frozen
