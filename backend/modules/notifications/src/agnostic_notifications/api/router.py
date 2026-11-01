"""HTTP routes: ``GET /api/v1/events`` (Server-Sent Events)."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.auth import Principal
from agnostic_notifications.application.stream import EventStream
from agnostic_notifications.settings import NotificationsSettings

router = APIRouter(route_class=DishkaRoute)


@router.get(
    "/events",
    summary="Realtime control-plane events for the signed-in person (text/event-stream)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def events(
    principal: FromDishka[Principal],
    stream: FromDishka[EventStream],
    settings: FromDishka[NotificationsSettings],
    session: FromDishka[AsyncSession],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> StreamingResponse:
    plan = await stream.plan(principal)
    # The stream can stay open for half an hour: don't hold a database connection while it does.
    await session.close()
    return StreamingResponse(
        stream.events(
            plan,
            last_event_id=last_event_id,
            heartbeat=settings.heartbeat_seconds,
            max_seconds=settings.max_stream_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
