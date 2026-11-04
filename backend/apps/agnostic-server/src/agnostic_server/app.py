"""Composition root: builds the FastAPI app from settings and the enabled modules."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import procrastinate
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel

from agnostic_kernel import __version__ as kernel_version
from agnostic_kernel.auth import HttpAuthProvider
from agnostic_kernel.container import Telemetry, build_container
from agnostic_kernel.errors import PROBLEM_RESPONSES, install_problem_handlers
from agnostic_kernel.health import health_router
from agnostic_kernel.http import RequestIdMiddleware
from agnostic_kernel.jobs import worker_options
from agnostic_kernel.logging import configure_logging, get_logger
from agnostic_kernel.modules import LoadedModules, RouterSpec, load_modules
from agnostic_kernel.settings import Settings
from agnostic_kernel.telemetry import configure_tracing, instrument_app
from agnostic_server import __version__

API_PREFIX = "/api/v1"

log = get_logger(__name__)


class ModuleInfo(BaseModel):
    name: str
    version: str
    depends_on: list[str]
    scopes: list[str]
    jobs: list[str]
    audit_actions: list[str]
    assistant_tools: list[str]


class SystemModules(BaseModel):
    enabled: list[ModuleInfo]
    disabled: list[str]


class SystemFeatures(BaseModel):
    features: dict[str, bool]
    """Control-plane features switched on right now (``assistant``, ``assistant.summaries``, …). A feature that is
    missing is off: its module is disabled, not installed or not configured."""


def operation_id(route: APIRoute) -> str:
    """Stable operation ids (``instances_list_instances``) so the generated TS client has readable names."""
    prefix = str(route.tags[0]) if route.tags else "api"
    return f"{prefix}_{route.name}"


def system_router(modules: LoadedModules, container: AsyncContainer) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/system/modules", summary="Enabled and disabled modules with what they contribute")
    async def list_modules() -> SystemModules:
        return SystemModules(
            enabled=[
                ModuleInfo(
                    name=m.name,
                    version=m.version,
                    depends_on=list(m.depends_on),
                    scopes=[s.name for s in m.scopes()],
                    jobs=[j.name for j in m.jobs()],
                    audit_actions=[a.action for a in m.audit_actions()],
                    assistant_tools=[t.name for t in m.assistant_tools()],
                )
                for m in modules.enabled
            ],
            disabled=list(modules.disabled),
        )

    @router.get("/system/features", summary="Control-plane features that are switched on")
    async def list_features() -> SystemFeatures:
        features: dict[str, bool] = {}
        async with container() as request:
            for module in modules.enabled:
                features.update(await module.features(request))
        return SystemFeatures(features=features)

    return router


@asynccontextmanager
async def _embedded_worker(container: AsyncContainer, settings: Settings) -> AsyncGenerator[None]:
    """Run the job worker inside the API process (``AGNOSTIC_JOBS__MODE=embedded``, the default on SQLite)."""
    jobs_app = await container.get(procrastinate.App)
    task = asyncio.create_task(
        jobs_app.run_worker_async(
            **worker_options(
                container,
                queues=settings.jobs.queues,
                concurrency=settings.jobs.concurrency,
                install_signal_handlers=False,
            )
        ),
        name="agnostic-embedded-worker",
    )
    log.info("jobs.embedded_worker_started", backend=settings.database.backend)
    try:
        yield
    finally:
        _ = task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app(
    settings: Settings | None = None,
    *,
    modules: LoadedModules | None = None,
    container: AsyncContainer | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log)
    modules = modules or load_modules(settings.modules.disabled)
    tracer_provider = configure_tracing(settings.otel)
    container = container or build_container(
        settings, modules, telemetry=Telemetry(tracer_provider), extra=(FastapiProvider(), HttpAuthProvider())
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        for module in modules.enabled:
            await module.on_startup(container)
        log.info("api.started", modules=modules.names(), database=settings.database.backend, jobs=settings.job_mode())
        try:
            if settings.job_mode() == "embedded":
                async with _embedded_worker(container, settings):
                    yield
            else:
                yield
        finally:
            for module in reversed(modules.enabled):
                await module.on_shutdown(container)
            await container.close()

    app = FastAPI(
        title="Agnostic",
        summary="Self-hosted control plane for Agno AgentOS",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    app.state.modules = modules

    api = APIRouter(prefix=API_PREFIX, responses=PROBLEM_RESPONSES)
    api.include_router(system_router(modules, container))
    root_specs: list[tuple[str, RouterSpec]] = []
    for module in modules.enabled:
        for spec in module.routers():
            if spec.root:
                root_specs.append((module.name, spec))
            else:
                api.include_router(spec.router, prefix=spec.prefix, tags=list(spec.tags or (module.name,)))
    app.include_router(api)
    for name, spec in root_specs:
        app.include_router(spec.router, prefix=spec.prefix, tags=list(spec.tags or (name,)))
    app.include_router(health_router())

    install_problem_handlers(app)
    if settings.http.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.http.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestIdMiddleware)
    setup_dishka(container, app)
    instrument_app(app, tracer_provider)
    log.debug("api.composed", kernel=kernel_version)
    return app
