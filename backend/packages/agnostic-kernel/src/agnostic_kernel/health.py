"""Liveness and readiness endpoints: ``/healthz`` and ``/readyz``."""

from typing import Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel.checks import check_cache, check_database, check_migrations
from agnostic_kernel.diagnostics import CheckResult
from agnostic_kernel.modules import LoadedModules
from agnostic_kernel.settings import Settings


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class Readiness(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    """``degraded``: the cache is down. The replica still serves (caches miss, realtime pauses), so it stays in
    rotation; alert on it from metrics or logs, not from readiness."""
    checks: list[ReadinessCheck]


def health_router() -> APIRouter:
    router = APIRouter(route_class=DishkaRoute, tags=["system"])

    @router.get("/healthz", operation_id="system_liveness")
    async def healthz() -> Liveness:
        return Liveness()

    @router.get(
        "/readyz",
        operation_id="system_readiness",
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Readiness}},
    )
    async def readyz(
        response: Response,
        engine: FromDishka[AsyncEngine],
        redis: FromDishka[Redis],
        modules: FromDishka[LoadedModules],
        settings: FromDishka[Settings],
    ) -> Readiness:
        cache = (
            CheckResult("cache", ok=True, detail="in-process store (single process, development only)")
            if settings.cache_backend() == "memory"
            else await check_cache(redis, probe=False)
        )
        database = await check_database(engine)
        migrations = await check_migrations(engine, list(modules.installed.values()))
        results = [database, cache, migrations]
        # Only what the API can't serve without takes a replica out of rotation: a cache outage would otherwise
        # drain every replica at once.
        ready = database.ok and migrations.ok
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(
            status="not_ready" if not ready else ("ready" if cache.ok else "degraded"),
            checks=[ReadinessCheck(name=r.name, ok=r.ok, detail=r.detail) for r in results],
        )

    return router
