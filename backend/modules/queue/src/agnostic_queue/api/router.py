"""HTTP routes: ``/api/v1/instances/{instance}/queue``."""

from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from agnostic_kernel.auth import Principal
from agnostic_queue.api.schemas import (
    QueueJobDetailOut,
    QueueJobOut,
    QueueJobsPageOut,
    QueueOverviewOut,
    QueueSummaryOut,
    QueueWorkerOut,
    RequeueIn,
    ResumeIn,
)
from agnostic_queue.application.operate import Queue

router = APIRouter(route_class=DishkaRoute)


@router.get("/{instance}/queue/summary", summary="Job counts for anyone with access to the instance")
async def queue_summary(instance: str, principal: FromDishka[Principal], queue: FromDishka[Queue]) -> QueueSummaryOut:
    return QueueSummaryOut.of(await queue.summary(principal, instance))


@router.get("/{instance}/queue/overview", summary="Queue health, config and workers (queue:operate or Instance admin)")
async def queue_overview(instance: str, principal: FromDishka[Principal], queue: FromDishka[Queue]) -> QueueOverviewOut:
    return QueueOverviewOut.of(await queue.overview(principal, instance))


@router.get("/{instance}/queue/workers", summary="Replicas with heartbeats and slots (queue:operate or Instance admin)")
async def queue_workers(
    instance: str, principal: FromDishka[Principal], queue: FromDishka[Queue]
) -> list[QueueWorkerOut]:
    return [QueueWorkerOut.of(worker) for worker in (await queue.overview(principal, instance)).workers]


@router.get("/{instance}/queue/jobs", summary="Durable jobs, newest first (queue:operate or Instance admin)")
async def queue_jobs(
    instance: str,
    principal: FromDishka[Principal],
    queue: FromDishka[Queue],
    status: Literal["queued", "running", "paused", "failed", "completed", "cancelled"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> QueueJobsPageOut:
    jobs, total, mode = await queue.jobs(principal, instance, status=status, page=page, limit=limit)
    return QueueJobsPageOut(
        data=[QueueJobOut.of(job) for job in jobs], page=page, limit=limit, total=total, access=mode
    )


@router.get("/{instance}/queue/jobs/{job_id}", summary="One job with its attempts and checkpoints")
async def queue_job(
    instance: str, job_id: str, principal: FromDishka[Principal], queue: FromDishka[Queue]
) -> QueueJobDetailOut:
    return QueueJobDetailOut.of_detail(await queue.job(principal, instance, job_id))


@router.post(
    "/{instance}/queue/jobs/{job_id}/resume",
    summary="Continue a failed run from a checkpoint; earlier tool calls aren't repeated (audited)",
)
async def resume_job(
    instance: str, job_id: str, principal: FromDishka[Principal], queue: FromDishka[Queue], body: ResumeIn
) -> QueueJobDetailOut:
    return QueueJobDetailOut.of_detail(await queue.resume(principal, instance, job_id, body.message_index))


@router.post("/{instance}/queue/jobs/{job_id}/requeue", summary="One more attempt with the same run id (audited)")
async def requeue_job(
    instance: str, job_id: str, principal: FromDishka[Principal], queue: FromDishka[Queue], body: RequeueIn
) -> QueueJobDetailOut:
    return QueueJobDetailOut.of_detail(await queue.requeue(principal, instance, job_id, force=body.force))


@router.post("/{instance}/queue/jobs/{job_id}/cancel", summary="Cancel a queued or running job's run (audited)")
async def cancel_job(
    instance: str, job_id: str, principal: FromDishka[Principal], queue: FromDishka[Queue]
) -> QueueJobDetailOut:
    return QueueJobDetailOut.of_detail(await queue.cancel(principal, instance, job_id))
