"""HTTP routes: ``GET /api/v1/search`` (the command palette)."""

from typing import Annotated

from dishka import AsyncContainer
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from agnostic_kernel.auth import Principal
from agnostic_search.api.schemas import SearchHitOut, SearchOut
from agnostic_search.application.ports import SearchIndex
from agnostic_search.application.use_cases import SearchEntities, reindex

router = APIRouter(route_class=DishkaRoute)


@router.get("/search", summary="Command-palette search over people, instances, agents, teams and workflows")
async def search(
    principal: FromDishka[Principal],
    use_case: FromDishka[SearchEntities],
    index: FromDishka[SearchIndex],
    container: FromDishka[AsyncContainer],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    instance: Annotated[str | None, Query(description="Instance id or slug: its components rank first")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    if await index.count() == 0:
        _ = await reindex(container)  # a fresh install: build the index on first use instead of waiting for the job
    hits = await use_case(principal, q, instance_ref=instance, limit=limit)
    return SearchOut(data=[SearchHitOut.from_hit(hit) for hit in hits])
