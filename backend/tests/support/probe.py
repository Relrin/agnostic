"""A minimal module for kernel tests: a route with a validated body, a background job that reports progress,
and cursor pagination. The kernel's contract is proven without shipping one.
"""

# No `from __future__ import annotations`: dishka wraps endpoints and FastAPI resolves annotations here.

from collections.abc import Iterable, Sequence
from typing import Annotated, Any, ClassVar

import procrastinate
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.jobs import JobProgressReporter, JobQueue, job_container
from agnostic_kernel.modules import (
    AuditActionDecl,
    BaseModule,
    JobSpec,
    LoadedModules,
    RouterSpec,
    ScopeDecl,
    discover_modules,
    resolve_modules,
)
from agnostic_kernel.pagination import Page, PageParams, encode_cursor, page_params
from agnostic_kernel.tables import JobProgressRow

ECHO_TASK = "probe.echo"
ITEMS = [f"item-{n}" for n in range(5)]

router = APIRouter(route_class=DishkaRoute)


class EchoIn(BaseModel):
    value: str = Field(min_length=1, max_length=100)


class JobOut(BaseModel):
    job_id: int
    progress: float | None = None
    message: str | None = None
    result: dict[str, Any] | None = None


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def start(body: EchoIn, queue: FromDishka[JobQueue]) -> JobOut:
    return JobOut(job_id=await queue.defer(ECHO_TASK, value=body.value))


@router.get("/jobs/{job_id}")
async def progress(job_id: int, session: FromDishka[AsyncSession]) -> JobOut:
    row = await session.get(JobProgressRow, job_id)
    if row is None:
        raise NotFoundError(f"Job {job_id} hasn't reported progress.")
    return JobOut(job_id=job_id, progress=row.progress, message=row.message, result=row.result)


@router.get("/items")
async def items(params: Annotated[PageParams, Depends(page_params)]) -> Page[str]:
    position = params.position()
    offset = position.get("offset") if position else 0
    begin = offset if isinstance(offset, int) else 0
    end = begin + params.limit
    return Page[str](data=ITEMS[begin:end], next_cursor=encode_cursor({"offset": end}) if end < len(ITEMS) else None)


async def echo(context: procrastinate.JobContext, value: str) -> None:
    job_id = context.job.id
    assert job_id is not None
    async with job_container(context) as container:
        reporter = await container.get(JobProgressReporter)
        await reporter.report(job_id, ECHO_TASK, 1.0, message="echoed", result={"echo": value})


class ProbeModule(BaseModule):
    name: ClassVar[str] = "probe"
    version: ClassVar[str] = "0.0.1"

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/probe", tags=("probe",)),)

    def jobs(self) -> Iterable[JobSpec]:
        return (JobSpec(name=ECHO_TASK, func=echo, retry=1),)

    def scopes(self) -> Iterable[ScopeDecl]:
        return (ScopeDecl("probe:read", "Read probe results"),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (AuditActionDecl("probe.echo", "{actor} echoed {value}"),)


def with_probe(disabled: Sequence[str] = ()) -> LoadedModules:
    """Every installed module plus the probe."""
    return resolve_modules([*discover_modules(), ProbeModule()], disabled)
