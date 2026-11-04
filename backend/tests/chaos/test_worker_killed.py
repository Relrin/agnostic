"""A worker process dies mid-job (OOM kill, node loss): its job stays ``doing`` with a silent heartbeat. Procrastinate
can find such jobs and retry them; the control plane has to ask it to."""

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import procrastinate
import pytest
from procrastinate.jobs import Status

from agnostic_kernel.container import build_container
from agnostic_kernel.modules import load_modules
from agnostic_kernel.testing import make_settings
from tests.chaos.stall_worker import BLOCK_TASK, HEARTBEAT_SECONDS, jobs_app
from tests.support.stack import migrate

pytestmark = pytest.mark.chaos

SCRIPT = Path(__file__).with_name("stall_worker.py")
STALLED_AFTER = 3 * HEARTBEAT_SECONDS


@pytest.fixture
async def database(fresh_postgres: str) -> str:
    await migrate(make_settings(fresh_postgres))
    return fresh_postgres


@pytest.fixture
async def app(database: str) -> AsyncIterator[procrastinate.App]:
    """The rest of the deployment: defers the job and, once retried, runs it to the end."""
    jobs = jobs_app(database)

    @jobs.task(name=BLOCK_TASK, pass_context=True)
    async def block(context: procrastinate.JobContext) -> None:  # pyright: ignore[reportUnusedFunction]
        _ = context

    async with jobs.open_async():
        yield jobs


@pytest.fixture
def doomed_worker(database: str) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), database],
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        yield process
    finally:
        process.kill()
        _ = process.wait(timeout=10)


async def status(app: procrastinate.App, job_id: int) -> Status:
    [job] = await app.job_manager.list_jobs_async(id=job_id)
    assert job.status is not None
    return Status(job.status)


async def until_status(app: procrastinate.App, job_id: int, wanted: Status, timeout: float = 20.0) -> None:  # noqa: ASYNC109
    deadline = time.monotonic() + timeout
    while (current := await status(app, job_id)) is not wanted:
        assert time.monotonic() < deadline, f"job {job_id} is {current.value}, not {wanted.value}"
        await asyncio.sleep(0.2)


async def stall_a_job(app: procrastinate.App, worker: subprocess.Popen[str]) -> int:
    job_id = await app.configure_task(BLOCK_TASK).defer_async()
    await until_status(app, job_id, Status.DOING)
    worker.kill()
    _ = worker.wait(timeout=10)
    await asyncio.sleep(STALLED_AFTER)
    return job_id


async def test_a_killed_workers_job_is_found_stalled_and_runs_again_once_retried(
    app: procrastinate.App, doomed_worker: subprocess.Popen[str]
) -> None:
    job_id = await stall_a_job(app, doomed_worker)
    assert await status(app, job_id) is Status.DOING  # nobody finishes or fails it on their own

    stalled = list(await app.job_manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_AFTER - 1))
    assert [job.id for job in stalled] == [job_id]
    for job in stalled:
        await app.job_manager.retry_job(job)
    await until_status(app, job_id, Status.TODO)

    await app.run_worker_async(wait=False, install_signal_handlers=False)
    assert await status(app, job_id) is Status.SUCCEEDED


async def test_the_control_plane_retries_stalled_jobs(database: str) -> None:
    settings = make_settings(database)
    container = build_container(settings, load_modules())
    try:
        jobs = await container.get(procrastinate.App)
        recovery = [name for name in jobs.tasks if "stalled" in name]
        periodic = {task.task.name for task in jobs.periodic_registry.periodic_tasks.values()}
    finally:
        await container.close()
    assert recovery, "no task retries stalled jobs"
    assert set(recovery) & periodic, "the stalled-job task isn't scheduled"
