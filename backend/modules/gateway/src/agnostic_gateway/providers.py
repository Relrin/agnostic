"""Dependency wiring of the gateway module."""

from __future__ import annotations

from collections.abc import AsyncIterator

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_gateway.application.ports import RoutePolicyRepository, Upstream
from agnostic_gateway.application.proxy import Gateway, GatewaySettingsView, InstanceCache, PolicyTableCache
from agnostic_gateway.application.streaming import CircuitBreaker
from agnostic_gateway.infrastructure.upstream import SqlRoutePolicyRepository, UpstreamPool
from agnostic_gateway.settings import GatewaySettings


class GatewayProvider(Provider):
    scope = Scope.REQUEST

    policies = provide(SqlRoutePolicyRepository, provides=RoutePolicyRepository)
    table_cache = provide(PolicyTableCache, scope=Scope.APP)
    instance_cache = provide(InstanceCache, scope=Scope.APP)
    gateway = provide(Gateway)

    @provide(scope=Scope.APP)
    def view(self, settings: GatewaySettings) -> GatewaySettingsView:
        return GatewaySettingsView(
            read_sample_rate=settings.read_sample_rate,
            rate_limits={
                "read": settings.rate_read_per_minute,
                "write": settings.rate_write_per_minute,
                "run": settings.rate_run_per_minute,
            },
            heartbeat_seconds=settings.heartbeat_seconds,
            max_body_bytes=settings.max_body_mb * 1024 * 1024,
        )

    @provide(scope=Scope.APP)
    def breaker(self, settings: GatewaySettings) -> CircuitBreaker:
        return CircuitBreaker(threshold=settings.circuit_failures, cooldown=settings.circuit_cooldown_seconds)

    @provide(scope=Scope.APP)
    async def upstream(self, settings: GatewaySettings) -> AsyncIterator[Upstream]:
        pool = UpstreamPool(read_timeout=settings.upstream_read_timeout)
        yield pool
        await pool.aclose()
