"""Liveness and readiness endpoints: ``/healthz`` and ``/readyz``."""

from typing import Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel.checks import CheckResult, check_cache, check_database, check_migrations
from agnostic_kernel.modules import LoadedModules
from agnostic_kernel.settings import Settings


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
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
        results = [
            await check_database(engine),
            cache,
            await check_migrations(engine, list(modules.installed.values())),
        ]
        ready = all(result.ok for result in results)
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(
            status="ready" if ready else "not_ready",
            checks=[ReadinessCheck(name=r.name, ok=r.ok, detail=r.detail) for r in results],
        )

    return router
