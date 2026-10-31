"""HTTP routes: ``/api/v1/hello/greetings``."""

# No `from __future__ import annotations`: dishka wraps endpoints, and FastAPI must resolve the
# annotations against this module (Python 3.15 evaluates annotations lazily anyway).

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, status

from agnostic_hello.api.schemas import GreetingCreate, GreetingOut
from agnostic_hello.application.use_cases import CreateGreeting, GetGreeting, ListGreetings
from agnostic_hello.domain.greeting import GREETING_ID_PREFIX
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import InvalidIdError, parse_id
from agnostic_kernel.pagination import Page, PageParams, encode_cursor, page_params

router = APIRouter(route_class=DishkaRoute)


@router.get("/greetings", summary="List greetings, newest first")
async def list_greetings(
    params: Annotated[PageParams, Depends(page_params)],
    use_case: FromDishka[ListGreetings],
) -> Page[GreetingOut]:
    position = params.position()
    after = position.get("after") if position else None
    page = await use_case(params.limit, after if isinstance(after, str) else None)
    return Page[GreetingOut](
        data=[GreetingOut.from_domain(item) for item in page.items],
        next_cursor=encode_cursor({"after": page.next_after_id}) if page.next_after_id else None,
    )


@router.post("/greetings", status_code=status.HTTP_201_CREATED, summary="Create a greeting and queue its reply")
async def create_greeting(body: GreetingCreate, use_case: FromDishka[CreateGreeting]) -> GreetingOut:
    return GreetingOut.from_domain(await use_case(body.message))


@router.get("/greetings/{greeting_id}", summary="Get one greeting")
async def get_greeting(greeting_id: str, use_case: FromDishka[GetGreeting]) -> GreetingOut:
    try:
        _ = parse_id(greeting_id, GREETING_ID_PREFIX)
    except InvalidIdError as exc:
        raise NotFoundError(f"Greeting {greeting_id} doesn't exist.") from exc
    return GreetingOut.from_domain(await use_case(greeting_id))
