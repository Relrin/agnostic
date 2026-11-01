"""HTTP routes: ``/api/v1/instances/{instance}/overview``."""

from typing import Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from agnostic_kernel.auth import Principal
from agnostic_observe.api.schemas import OverviewOut
from agnostic_observe.application.overview import GetOverview

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/{instance}/overview",
    summary="Home: what needs attention, KPIs, runs per day, model usage, primitives and recent activity",
)
async def overview(
    instance: str,
    principal: FromDishka[Principal],
    use_case: FromDishka[GetOverview],
    range: Literal["24h", "7d", "30d"] = "7d",  # noqa: A002  (the public query parameter name)
    refresh: bool = False,
) -> OverviewOut:
    return OverviewOut.from_domain(await use_case(principal, instance, range, refresh=refresh))
