"""Dependency injection: kernel services plus every enabled module's providers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass

import procrastinate
from dishka import (
    AsyncContainer,
    Provider,
    Scope,
    from_context,
    make_async_container,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from opentelemetry.sdk.trace import TracerProvider
from pydantic_settings import BaseSettings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agnostic_kernel.cache import create_redis
from agnostic_kernel.crypto import SecretBox, load_master_key
from agnostic_kernel.db import create_engine, create_sessionmaker
from agnostic_kernel.ephemeral import EphemeralStore, MemoryStore, RedisStore
from agnostic_kernel.jobs import JobProgressReporter, JobQueue, create_jobs_app, register_jobs
from agnostic_kernel.mail import Mailer, create_mailer
from agnostic_kernel.modules import LoadedModules
from agnostic_kernel.settings import Settings
from agnostic_kernel.telemetry import instrument_engine


@dataclass(frozen=True, slots=True)
class Telemetry:
    tracer_provider: TracerProvider | None = None


class KernelProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)
    modules = from_context(provides=LoadedModules, scope=Scope.APP)
    telemetry = from_context(provides=Telemetry, scope=Scope.APP)

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings, telemetry: Telemetry) -> AsyncIterator[AsyncEngine]:
        engine = create_engine(settings.database)
        instrument_engine(engine, telemetry.tracer_provider)
        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    def sessionmaker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return create_sessionmaker(engine)

    @provide(scope=Scope.REQUEST)
    async def session(self, sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    @provide(scope=Scope.APP)
    async def redis(self, settings: Settings) -> AsyncIterator[Redis]:
        client = create_redis(settings.redis)
        yield client
        await client.aclose()

    @provide(scope=Scope.APP)
    def ephemeral(self, settings: Settings, redis: Redis) -> EphemeralStore:
        if settings.cache_backend() == "memory":
            return MemoryStore()
        return RedisStore(redis)

    @provide(scope=Scope.APP)
    def secret_box(self, settings: Settings) -> SecretBox:
        return SecretBox(load_master_key(settings.secrets, environment=settings.env))

    @provide(scope=Scope.APP)
    def mailer(self, settings: Settings) -> Mailer:
        return create_mailer(settings.smtp)

    @provide(scope=Scope.APP)
    async def jobs_app(self, settings: Settings, modules: LoadedModules) -> AsyncIterator[procrastinate.App]:
        app = create_jobs_app(settings.database)
        _ = register_jobs(app, (spec for module in modules.enabled for spec in module.jobs()))
        async with app.open_async():
            yield app

    job_queue = provide(JobQueue, scope=Scope.APP)
    job_progress = provide(JobProgressReporter, scope=Scope.APP)


def module_settings_provider(models: Iterable[type[BaseSettings]]) -> Provider:
    """Expose each module's settings model as an APP-scoped dependency."""
    provider = Provider(scope=Scope.APP)
    for model in models:
        provider.provide(_settings_factory(model), provides=model)
    return provider


def _settings_factory(model: type[BaseSettings]) -> Callable[[], BaseSettings]:
    def factory() -> BaseSettings:
        return model()

    return factory


def build_container(
    settings: Settings,
    modules: LoadedModules,
    *,
    telemetry: Telemetry | None = None,
    extra: Iterable[Provider] = (),
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """Build the app container.

    Order: kernel providers, ``extra`` (e.g. the FastAPI integration), every enabled module's providers, then
    ``overrides`` (tests swap adapters there: later providers win).
    """
    settings_models = [m for module in modules.enabled if (m := module.settings_model()) is not None]
    providers: list[Provider] = [KernelProvider(), module_settings_provider(settings_models), *extra]
    for module in modules.enabled:
        providers.extend(module.provide())
    providers.extend(overrides)
    return make_async_container(
        *providers,
        context={Settings: settings, LoadedModules: modules, Telemetry: telemetry or Telemetry()},
    )
