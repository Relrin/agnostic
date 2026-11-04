"""``agnostic worker``: runs module jobs and periodic schedules."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Coroutine
from types import FrameType
from typing import Any

import procrastinate

from agnostic_kernel import metrics
from agnostic_kernel.container import Telemetry, build_container
from agnostic_kernel.job_admin import JobAdmin, refresh_job_metrics
from agnostic_kernel.jobs import keep_working, worker_options
from agnostic_kernel.logging import configure_logging, get_logger
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_kernel.telemetry import configure_tracing
from agnostic_server import __version__

log = get_logger(__name__)


class WorkerUnavailableError(RuntimeError):
    pass


async def _until_signalled(work: Coroutine[Any, Any, None]) -> None:
    """Run ``work`` until SIGINT/SIGTERM, then cancel it (Procrastinate finishes running jobs gracefully)."""
    task = asyncio.create_task(work, name="agnostic-worker")
    loop = asyncio.get_running_loop()

    def stop(_signum: int, _frame: FrameType | None) -> None:
        _ = loop.call_soon_threadsafe(task.cancel)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, task.cancel)
        except NotImplementedError, RuntimeError:  # Windows event loops: plain signal handlers instead
            _ = signal.signal(signum, stop)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("worker.stopped_by_signal")


async def run_worker(settings: Settings, *, queues: list[str] | None = None, concurrency: int | None = None) -> None:
    if settings.database.backend != "postgresql":
        msg = (
            "A separate worker needs PostgreSQL (Procrastinate). With SQLite, jobs run inside `agnostic api` "
            "(AGNOSTIC_JOBS__MODE=embedded)."
        )
        raise WorkerUnavailableError(msg)
    configure_logging(settings.log)
    modules = load_modules(settings.modules.disabled)
    container = build_container(settings, modules, telemetry=Telemetry(configure_tracing(settings.otel)))
    try:
        for module in modules.enabled:
            await module.on_startup(container)
        jobs_app = await container.get(procrastinate.App)
        selected = queues or settings.jobs.queues or None
        log.info("worker.started", modules=modules.names(), queues=selected or "all")
        metrics.info.labels(__version__).set(1)
        metrics.serve_metrics(settings.metrics)
        admin = await container.get(JobAdmin)
        options = worker_options(
            container,
            queues=selected,
            concurrency=concurrency or settings.jobs.concurrency,
            install_signal_handlers=False,
        )
        async with metrics.refreshing(lambda: refresh_job_metrics(admin), every=30.0):
            await _until_signalled(keep_working(jobs_app, options))
    finally:
        for module in reversed(modules.enabled):
            await module.on_shutdown(container)
        await container.close()
