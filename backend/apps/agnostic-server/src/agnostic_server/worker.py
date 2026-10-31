"""``agnostic worker``: runs module jobs and periodic schedules."""

from __future__ import annotations

import procrastinate

from agnostic_kernel.container import Telemetry, build_container
from agnostic_kernel.jobs import worker_options
from agnostic_kernel.logging import configure_logging, get_logger
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_kernel.telemetry import configure_tracing

log = get_logger(__name__)


class WorkerUnavailableError(RuntimeError):
    pass


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
        await jobs_app.run_worker_async(
            **worker_options(container, queues=selected, concurrency=concurrency or settings.jobs.concurrency)
        )
    finally:
        for module in reversed(modules.enabled):
            await module.on_shutdown(container)
        await container.close()
