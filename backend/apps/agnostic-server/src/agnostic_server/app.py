"""Composition root: builds the FastAPI app from settings and the enabled modules."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import procrastinate
from dishka import AsyncContainer
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from agnostic_kernel import __version__ as kernel_version
from agnostic_kernel import metrics
from agnostic_kernel.auth import HttpAuthProvider
from agnostic_kernel.container import Telemetry, build_container
from agnostic_kernel.errors import PROBLEM_RESPONSES, install_problem_handlers
from agnostic_kernel.health import health_router
from agnostic_kernel.http import RequestIdMiddleware
from agnostic_kernel.job_admin import JobAdmin, refresh_job_metrics
from agnostic_kernel.jobs import worker_options
from agnostic_kernel.logging import configure_logging, get_logger
from agnostic_kernel.modules import LoadedModules, RouterSpec, load_modules
from agnostic_kernel.security_headers import ConnectSources, SecurityHeadersMiddleware
from agnostic_kernel.settings import Settings
from agnostic_kernel.telemetry import configure_tracing, instrument_app
from agnostic_server import __version__
from agnostic_server.web import Guides, WebApp, guides_router, reserved_segments

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


class SystemInfo(BaseModel):
    version: str
    environment: str
    docs_available: bool = Field(description="User guides are bundled (in-product help works offline)")
    web_app: bool = Field(description="The API serves the web app on this origin")


class SystemFeatures(BaseModel):
    features: dict[str, bool]
    """Control-plane features switched on right now (``assistant``, ``assistant.summaries``, …). A feature that is
    missing is off: its module is disabled, not installed or not configured."""


def operation_id(route: APIRoute) -> str:
    """Stable operation ids (``instances_list_instances``) so the generated TS client has readable names."""
    prefix = str(route.tags[0]) if route.tags else "api"
    return f"{prefix}_{route.name}"


def system_router(modules: LoadedModules, container: AsyncContainer, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/system/info", summary="Version and what this installation bundles")
    async def system_info() -> SystemInfo:
        docs = settings.http.docs_dir
        return SystemInfo(
            version=__version__,
            environment=settings.env,
            docs_available=docs is not None and docs.is_dir(),
            web_app=settings.http.web_dir is not None,
        )

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


def _lifespan(
    settings: Settings, modules: LoadedModules, container: AsyncContainer
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        for module in modules.enabled:
            await module.on_startup(container)
        log.info("api.started", modules=modules.names(), database=settings.database.backend, jobs=settings.job_mode())
        metrics.info.labels(__version__).set(1)
        admin = await container.get(JobAdmin)
        try:
            async with contextlib.AsyncExitStack() as stack:
                if settings.metrics.enabled:
                    await stack.enter_async_context(metrics.refreshing(lambda: refresh_job_metrics(admin)))
                if settings.job_mode() == "embedded":
                    await stack.enter_async_context(_embedded_worker(container, settings))
                yield
        finally:
            for module in reversed(modules.enabled):
                await module.on_shutdown(container)
            await container.close()

    return lifespan


def _include_routers(app: FastAPI, settings: Settings, modules: LoadedModules, container: AsyncContainer) -> set[str]:
    """Mount every router; returns the first path segments the API owns (the web app gets everything else)."""
    api = APIRouter(prefix=API_PREFIX, responses=PROBLEM_RESPONSES)
    api.include_router(system_router(modules, container, settings))
    api.include_router(guides_router(Guides(settings.http.docs_dir)))
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
    if settings.metrics.enabled and settings.metrics.token is not None:
        # On the main port only behind a token: the ingress routes this port, the metrics port it doesn't.
        app.add_route("/metrics", metrics.metrics_endpoint(settings.metrics), include_in_schema=False)
    owned = [API_PREFIX, "/healthz", "/readyz", "/metrics", "/docs"]
    owned += [spec.prefix + str(getattr(route, "path", "")) for _, spec in root_specs for route in spec.router.routes]
    return reserved_segments(owned)


def _install_middleware(app: FastAPI, settings: Settings, container: AsyncContainer, owned: set[str]) -> None:
    """Outermost last: metrics see everything, security headers land on every response (the web app's too)."""
    if settings.http.web_dir is not None:
        app.add_middleware(WebApp, web_dir=settings.http.web_dir, reserved=owned)
    if settings.http.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.http.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestIdMiddleware)

    async def connect_origins() -> tuple[str, ...]:
        return await (await container.get(ConnectSources)).origins()

    app.add_middleware(SecurityHeadersMiddleware, settings=settings, connect=connect_origins)
    if settings.metrics.enabled:
        app.add_middleware(metrics.MetricsMiddleware)


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
    app = FastAPI(
        title="Agnostic",
        summary="Self-hosted control plane for Agno AgentOS",
        version=__version__,
        lifespan=_lifespan(settings, modules, container),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    app.state.modules = modules
    owned = _include_routers(app, settings, modules, container)
    install_problem_handlers(app)
    _install_middleware(app, settings, container, owned)
    setup_dishka(container, app)
    instrument_app(app, tracer_provider)
    log.debug("api.composed", kernel=kernel_version)
    return app
