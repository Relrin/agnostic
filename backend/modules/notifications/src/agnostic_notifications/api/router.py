"""HTTP routes: ``GET /api/v1/events`` (Server-Sent Events), ``/api/v1/notifications`` and personal preferences."""

from datetime import datetime
from typing import Annotated, Any

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import ValidationFailedError
from agnostic_kernel.pagination import Page, PageParams, encode_cursor, page_params
from agnostic_notifications.api.schemas import (
    ChannelIn,
    ChannelOut,
    ChannelPatch,
    DefaultsBody,
    DeliveryOut,
    EventTypeOut,
    MarkReadIn,
    MarkReadOut,
    NotificationOut,
    PreferencesIn,
    PreferencesOut,
    UnreadOut,
    catalog,
)
from agnostic_notifications.application.manage import ChannelDraft, Channels, ChannelView, Inbox, Preferences
from agnostic_notifications.application.stream import EventStream
from agnostic_notifications.settings import NotificationsSettings

router = APIRouter(route_class=DishkaRoute)
me_router = APIRouter(route_class=DishkaRoute)


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


@router.get("/notifications", summary="Your notifications (the bell), newest first")
async def list_notifications(
    principal: FromDishka[Principal],
    inbox: FromDishka[Inbox],
    params: Annotated[PageParams, Depends(page_params)],
    unread: Annotated[bool, Query(description="Only unread ones")] = False,
) -> Page[NotificationOut]:
    position = params.position()
    before: tuple[datetime, str] | None = None
    if position is not None:
        try:
            before = (datetime.fromisoformat(str(position["t"])), str(position["id"]))
        except (KeyError, ValueError) as exc:
            raise ValidationFailedError("The cursor is malformed.") from exc
    items = await inbox.page(principal, limit=params.limit + 1, before=before, unread_only=unread)
    shown = items[: params.limit]
    cursor = (
        encode_cursor({"t": shown[-1].created_at.isoformat(), "id": shown[-1].id})
        if len(items) > params.limit
        else None
    )
    return Page[NotificationOut](data=[NotificationOut.of(item) for item in shown], next_cursor=cursor)


@router.get("/notifications/unread-count", summary="How many of your notifications are unread (the bell badge)")
async def unread_count(principal: FromDishka[Principal], inbox: FromDishka[Inbox]) -> UnreadOut:
    return UnreadOut(unread=await inbox.unread(principal))


@router.post("/notifications/read", summary="Mark some or all of your notifications read")
async def mark_read(principal: FromDishka[Principal], inbox: FromDishka[Inbox], body: MarkReadIn) -> MarkReadOut:
    changed = await inbox.mark_read(principal, body.ids)
    return MarkReadOut(changed=changed, unread=await inbox.unread(principal))


@router.get("/notifications/event-types", summary="Everything that can be notified, with its default channels")
async def event_types() -> list[EventTypeOut]:
    return catalog()


@router.get("/notifications/defaults", summary="Org default channels per event type (needs notifications:write)")
async def get_defaults(principal: FromDishka[Principal], preferences: FromDishka[Preferences]) -> DefaultsBody:
    values = await preferences.defaults(principal)
    return DefaultsBody(events={name: list(channels) for name, channels in values.items()})  # pyright: ignore[reportArgumentType]


@router.put("/notifications/defaults", summary="Change org default channels (needs notifications:write; audited)")
async def put_defaults(
    principal: FromDishka[Principal], preferences: FromDishka[Preferences], body: DefaultsBody
) -> DefaultsBody:
    values = await preferences.update_defaults(principal, body.events)
    return DefaultsBody(events={name: list(channels) for name, channels in values.items()})  # pyright: ignore[reportArgumentType]


@router.get("/notifications/channels", summary="Org notification channels (needs notifications:write)")
async def list_channels(principal: FromDishka[Principal], channels: FromDishka[Channels]) -> list[ChannelOut]:
    return [ChannelOut.of(view) for view in await channels.list(principal)]


@router.post("/notifications/channels", status_code=201, summary="Add a Slack, email or webhook channel")
async def create_channel(
    principal: FromDishka[Principal], channels: FromDishka[Channels], body: ChannelIn
) -> ChannelOut:
    channel = await channels.create(
        principal,
        ChannelDraft(
            kind=body.kind,
            name=body.name,
            config=body.config,
            events=body.events,
            instance_ids=body.instance_ids,
            enabled=body.enabled,
        ),
    )
    return ChannelOut.of(ChannelView(channel, []))


@router.get("/notifications/channels/{channel_id}", summary="One channel with its recent deliveries")
async def get_channel(principal: FromDishka[Principal], channels: FromDishka[Channels], channel_id: str) -> ChannelOut:
    return ChannelOut.of(await channels.get(principal, channel_id))


@router.patch("/notifications/channels/{channel_id}", summary="Change a channel (secrets left out are kept)")
async def update_channel(
    principal: FromDishka[Principal], channels: FromDishka[Channels], channel_id: str, body: ChannelPatch
) -> ChannelOut:
    changes: dict[str, Any] = body.model_dump(exclude_unset=True)
    await channels.update(principal, channel_id, changes)
    return ChannelOut.of(await channels.get(principal, channel_id))


@router.delete("/notifications/channels/{channel_id}", status_code=204, summary="Remove a channel")
async def delete_channel(principal: FromDishka[Principal], channels: FromDishka[Channels], channel_id: str) -> Response:
    await channels.delete(principal, channel_id)
    return Response(status_code=204)


@router.post("/notifications/channels/{channel_id}/test", summary="Send a test message now and report the outcome")
async def test_channel(
    principal: FromDishka[Principal], channels: FromDishka[Channels], channel_id: str
) -> DeliveryOut:
    return DeliveryOut.of(await channels.test(principal, channel_id))


@me_router.get("/notification-preferences", summary="Which channels each event reaches you through, and quiet hours")
async def my_preferences(principal: FromDishka[Principal], preferences: FromDishka[Preferences]) -> PreferencesOut:
    return PreferencesOut.of(await preferences.mine(principal))


@me_router.put("/notification-preferences", summary="Change your notification channels or quiet hours")
async def update_my_preferences(
    principal: FromDishka[Principal], preferences: FromDishka[Preferences], body: PreferencesIn
) -> PreferencesOut:
    value = await preferences.update_mine(
        principal,
        body.events,
        quiet_hours=body.quiet_hours.model_dump() if body.quiet_hours else None,
        clear_quiet_hours=body.clear_quiet_hours,
    )
    return PreferencesOut.of(value)
