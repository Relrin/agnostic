"""HTTP routes: ``/api/v1/instances/{instance}/schedules``."""

from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response

from agnostic_kernel.auth import Principal
from agnostic_scheduler.api.schemas import (
    DisableIn,
    EndpointCheckOut,
    PreviewIn,
    PreviewOut,
    RunsPageOut,
    ScheduleIn,
    ScheduleOut,
    SchedulePatch,
    SchedulerStatusOut,
    ScheduleRunOut,
    SchedulesPageOut,
)
from agnostic_scheduler.application.schedules import Schedules

router = APIRouter(route_class=DishkaRoute)


@router.get("/{instance}/schedules", summary="Schedules with their latest runs (needs schedules:read)")
async def list_schedules(
    instance: str,
    principal: FromDishka[Principal],
    schedules: FromDishka[Schedules],
    enabled: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SchedulesPageOut:
    views, total = await schedules.list(principal, instance, enabled=enabled, page=page, limit=limit)
    return SchedulesPageOut(data=[ScheduleOut.of(view) for view in views], page=page, limit=limit, total=total)


@router.post(
    "/{instance}/schedules",
    status_code=201,
    summary="Create a schedule (schedules:write; a custom endpoint needs Instance admin)",
)
async def create_schedule(
    instance: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules], body: ScheduleIn
) -> ScheduleOut:
    return ScheduleOut.of(await schedules.create(principal, instance, body.model_dump()))


@router.post("/{instance}/schedules/preview", summary="A cron expression as a sentence, its next runs, DST notes")
async def preview_schedule(
    instance: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules], body: PreviewIn
) -> PreviewOut:
    value = await schedules.preview(
        principal, instance, body.cron_expr, body.timezone, count=body.count, start=body.start
    )
    return PreviewOut.of(value)


@router.get("/{instance}/schedules/status", summary="Whether the scheduler runs, and what you may do here")
async def scheduler_status(
    instance: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules]
) -> SchedulerStatusOut:
    return SchedulerStatusOut.of(await schedules.status(principal, instance))


@router.get(
    "/{instance}/schedules/endpoint-check",
    summary="What an endpoint targets, and whether the instance's OpenAPI document knows it",
)
async def check_endpoint(
    instance: str,
    principal: FromDishka[Principal],
    schedules: FromDishka[Schedules],
    path: Annotated[str, Query(max_length=512, pattern=r"^/")],
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST",
) -> EndpointCheckOut:
    return EndpointCheckOut.of(await schedules.endpoint_check(principal, instance, method, path))


@router.get("/{instance}/schedules/{schedule_id}", summary="One schedule with its recent runs")
async def get_schedule(
    instance: str, schedule_id: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules]
) -> ScheduleOut:
    return ScheduleOut.of(await schedules.get(principal, instance, schedule_id))


@router.patch("/{instance}/schedules/{schedule_id}", summary="Change a schedule (schedules:write)")
async def update_schedule(
    instance: str,
    schedule_id: str,
    principal: FromDishka[Principal],
    schedules: FromDishka[Schedules],
    body: SchedulePatch,
) -> ScheduleOut:
    return ScheduleOut.of(await schedules.update(principal, instance, schedule_id, body.model_dump(exclude_unset=True)))


@router.delete("/{instance}/schedules/{schedule_id}", status_code=204, summary="Delete a schedule (schedules:delete)")
async def delete_schedule(
    instance: str, schedule_id: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules]
) -> Response:
    await schedules.delete(principal, instance, schedule_id)
    return Response(status_code=204)


@router.post("/{instance}/schedules/{schedule_id}/enable", summary="Enable a schedule (schedules:write)")
async def enable_schedule(
    instance: str, schedule_id: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules]
) -> ScheduleOut:
    return ScheduleOut.of(await schedules.enable(principal, instance, schedule_id))


@router.post(
    "/{instance}/schedules/{schedule_id}/disable", summary="Disable a schedule, with a reason (schedules:write)"
)
async def disable_schedule(
    instance: str,
    schedule_id: str,
    principal: FromDishka[Principal],
    schedules: FromDishka[Schedules],
    body: DisableIn,
) -> ScheduleOut:
    return ScheduleOut.of(await schedules.disable(principal, instance, schedule_id, body.reason))


@router.post("/{instance}/schedules/{schedule_id}/trigger", summary="Run a schedule now (schedules:write)")
async def trigger_schedule(
    instance: str, schedule_id: str, principal: FromDishka[Principal], schedules: FromDishka[Schedules]
) -> ScheduleRunOut:
    return ScheduleRunOut.of(await schedules.trigger(principal, instance, schedule_id))


@router.get("/{instance}/schedules/{schedule_id}/runs", summary="Run history of a schedule, newest first")
async def schedule_runs(
    instance: str,
    schedule_id: str,
    principal: FromDishka[Principal],
    schedules: FromDishka[Schedules],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunsPageOut:
    result = await schedules.runs(principal, instance, schedule_id, page=page, limit=limit)
    return RunsPageOut(data=[ScheduleRunOut.of(run) for run in result.runs], page=page, limit=limit, total=result.total)
