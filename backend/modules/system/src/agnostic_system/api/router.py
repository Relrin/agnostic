"""HTTP routes of the System page: ``/api/v1/system/status``, ``/checks`` and failed jobs."""

from datetime import datetime
from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from agnostic_kernel.auth import Principal
from agnostic_system.application.status import SystemStatus

router = APIRouter(route_class=DishkaRoute)


class VersionsOut(BaseModel):
    server: str
    python: str
    database: str
    cache: str
    modules: dict[str, str]


class QueueOut(BaseModel):
    queue: str
    waiting: int
    running: int
    failed: int
    oldest_wait_seconds: float | None = Field(description="Age of the oldest due job not picked up yet")


class CacheOut(BaseModel):
    backend: str
    hits: int
    misses: int
    hit_ratio: float | None = Field(description="Since this API process started")


class InstancePollOut(BaseModel):
    id: str
    slug: str
    display_name: str
    status: str
    last_seen_at: datetime | None
    latency_ms: int | None
    network_mode: str


class StatusItemOut(BaseModel):
    group: str
    name: str
    state: Literal["ok", "warning", "error"]
    detail: str
    facts: dict[str, str]


class SystemStatusOut(BaseModel):
    environment: str
    versions: VersionsOut
    queues: list[QueueOut]
    cache: CacheOut
    instances: list[InstancePollOut]
    items: list[StatusItemOut]


class CheckOut(BaseModel):
    name: str
    ok: bool
    detail: str
    facts: dict[str, str]


class FailedJobOut(BaseModel):
    id: int
    queue: str
    task: str
    attempts: int
    failed_at: datetime | None
    argument_names: list[str]


@router.get("/status", summary="System overview: versions, job queues, cache, instance polling, backlogs")
async def system_status(principal: FromDishka[Principal], system: FromDishka[SystemStatus]) -> SystemStatusOut:
    overview = await system.overview(principal)
    return SystemStatusOut(
        environment=overview.environment,
        versions=VersionsOut(
            server=overview.versions.server,
            python=overview.versions.python,
            database=overview.versions.database,
            cache=overview.versions.cache,
            modules=overview.versions.modules,
        ),
        queues=[
            QueueOut(
                queue=item.queue,
                waiting=item.waiting,
                running=item.running,
                failed=item.failed,
                oldest_wait_seconds=item.oldest_wait_seconds,
            )
            for item in overview.queues
        ],
        cache=CacheOut(
            backend=overview.cache.backend,
            hits=overview.cache.hits,
            misses=overview.cache.misses,
            hit_ratio=overview.cache.hit_ratio,
        ),
        instances=[
            InstancePollOut(
                id=item.id,
                slug=item.slug,
                display_name=item.display_name,
                status=item.status.value,
                last_seen_at=item.last_seen_at,
                latency_ms=item.latency_ms,
                network_mode=item.network_mode.value,
            )
            for item in overview.instances
        ],
        items=[
            StatusItemOut(group=item.group, name=item.name, state=item.state, detail=item.detail, facts=item.facts)
            for item in overview.items
        ],
    )


@router.post("/checks", summary="Probe every endpoint now (database, cache, master key, SMTP, IdPs, runtimes, …)")
async def run_checks(principal: FromDishka[Principal], system: FromDishka[SystemStatus]) -> list[CheckOut]:
    return [
        CheckOut(name=result.name, ok=result.ok, detail=result.detail, facts=result.facts)
        for result in await system.checks(principal)
    ]


@router.get("/jobs/failed", summary="Failed background jobs (newest first)")
async def list_failed_jobs(
    principal: FromDishka[Principal],
    system: FromDishka[SystemStatus],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[int | None, Query(description="Page: jobs with a smaller id")] = None,
) -> list[FailedJobOut]:
    jobs = await system.failed_jobs(principal, limit=limit, before=before)
    return [
        FailedJobOut(
            id=job.id,
            queue=job.queue,
            task=job.task,
            attempts=job.attempts,
            failed_at=job.failed_at,
            argument_names=list(job.argument_names),
        )
        for job in jobs
    ]


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_204_NO_CONTENT, summary="Run a failed job again")
async def retry_job(job_id: int, principal: FromDishka[Principal], system: FromDishka[SystemStatus]) -> None:
    await system.retry(principal, job_id)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Discard a failed job")
async def discard_job(job_id: int, principal: FromDishka[Principal], system: FromDishka[SystemStatus]) -> None:
    await system.discard(principal, job_id)
