"""Fan one event out: the bell of every recipient, their email or Slack DM, and the org channels that listen.

The inbox rows and delivery records are written in one transaction; after the commit each delivery is handed to the
``notifications.deliver`` job (retried there), and the bell updates over ``notification.created``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from agnostic_identity.facade import IdentityFacade, User
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus, RealtimeEvent, user_channel
from agnostic_kernel.jobs import JobQueue
from agnostic_kernel.logging import get_logger
from agnostic_notifications.application.ports import Delivery, Repositories
from agnostic_notifications.domain.catalog import event_type, personal_channels
from agnostic_notifications.domain.channels import Channel
from agnostic_notifications.domain.messages import Action, Message

log = get_logger(__name__)

DELIVER_TASK = "notifications.deliver"
DEDUPE_TTL = 7 * 24 * 3600


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    event_type: str
    """One of :data:`agnostic_notifications.domain.catalog.EVENT_TYPES`."""
    title: str
    body: str = ""
    link: str | None = None
    """An app path (``/i/prod/approvals?approval=apv_1``); channels outside the app get the absolute URL."""
    instance_id: str | None = None
    recipients: Sequence[str] = ()
    """User ids. Unknown or inactive users are skipped."""
    channel_ids: Sequence[str] = ()
    """Org channels to post to whether or not they subscribe to the event (approval routes)."""
    forced_channels: Sequence[str] = ()
    """Personal channels added for every recipient (a route that says "Slack + control plane")."""
    actions: Sequence[tuple[str, str, str]] = ()
    """``(label, app path, style)`` buttons for Slack and links for email."""
    context: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])
    dedupe_key: str | None = None
    """The same key notifies once (a watcher that sees the same approval twice)."""


@dataclass(frozen=True, slots=True)
class NotifyResult:
    inbox: int
    deliveries: int
    skipped: bool = False


class Notify:
    def __init__(
        self,
        repositories: Repositories,
        identity: IdentityFacade,
        queue: JobQueue,
        bus: EventBus,
        store: EphemeralStore,
        public_url: str,
    ) -> None:
        self._repos = repositories
        self._identity = identity
        self._queue = queue
        self._bus = bus
        self._store = store
        self._public_url = public_url.rstrip("/")

    def absolute(self, path: str | None) -> str | None:
        if path is None:
            return None
        return path if path.startswith(("http://", "https://")) else f"{self._public_url}/{path.lstrip('/')}"

    def message(self, request: NotificationRequest) -> Message:
        return Message(
            event_type=request.event_type,
            title=request.title,
            body=request.body,
            url=self.absolute(request.link),
            actions=tuple(Action(label, self.absolute(path) or path, style) for label, path, style in request.actions),  # pyright: ignore[reportArgumentType]
            context=request.context,
            data=dict(request.data),
        )

    async def __call__(self, request: NotificationRequest) -> NotifyResult:
        _ = event_type(request.event_type)
        if request.dedupe_key and not await self._store.set_if_absent(
            f"ntf:dedupe:{request.dedupe_key}", b"1", ttl=DEDUPE_TTL
        ):
            return NotifyResult(inbox=0, deliveries=0, skipped=True)
        message = self.message(request)
        channels = await self._repos.channels.list()
        defaults = await self._repos.preferences.defaults()
        bot = next((channel for channel in channels if channel.enabled and channel.sends_direct_messages), None)
        now = utcnow()

        inbox_for: list[str] = []
        deliveries: list[Delivery] = []
        users = [user for user in await self._identity.get_users(sorted(set(request.recipients))) if user.active]
        for user in users:
            preferences = await self._repos.preferences.for_user(user.id)
            reach = personal_channels(
                request.event_type,
                preference=preferences.get(request.event_type),
                org_default=defaults.get(request.event_type),
                quiet=await self._repos.preferences.quiet_hours(user.id),
                now=now,
                forced=request.forced_channels,
            )
            if "in_app" in reach:
                _ = await self._repos.inbox.add(
                    user_id=user.id,
                    kind=request.event_type,
                    title=request.title,
                    body=request.body,
                    link=request.link,
                    instance_id=request.instance_id,
                    payload=dict(request.data),
                )
                inbox_for.append(user.id)
            deliveries.extend(await self._personal(user, reach, bot, message))

        named = set(request.channel_ids)
        listening = [
            channel
            for channel in channels
            if channel.enabled and (channel.id in named or channel.receives(request.event_type, request.instance_id))
        ]
        deliveries.extend([await self._broadcast(channel, message) for channel in listening])
        await self._repos.commit()

        for user_id in inbox_for:
            await self._bus.publish(
                user_channel(user_id),
                RealtimeEvent(
                    "notification.created",
                    {"kind": request.event_type, "title": request.title, "link": request.link},
                    instance_id=None,
                ),
            )
        for delivery in deliveries:
            try:
                _ = await self._queue.defer(DELIVER_TASK, delivery_id=delivery.id)
            except Exception as exc:  # noqa: BLE001  (the record stays pending; the bell already has it)
                log.warning("notifications.defer_failed", delivery=delivery.id, error=str(exc))
        return NotifyResult(inbox=len(inbox_for), deliveries=len(deliveries))

    async def _personal(
        self, user: User, reach: Sequence[str], bot: Channel | None, message: Message
    ) -> list[Delivery]:
        created: list[Delivery] = []
        if "email" in reach:
            created.append(
                await self._repos.deliveries.add(
                    event_type=message.event_type,
                    channel="email",
                    channel_id=None,
                    user_id=user.id,
                    target=user.email,
                    message=message.to_dict(),
                )
            )
        if "slack" in reach:
            if bot is None:
                log.info("notifications.slack_dm_unavailable", user=user.id, notification=message.event_type)
            else:
                created.append(
                    await self._repos.deliveries.add(
                        event_type=message.event_type,
                        channel="slack_dm",
                        channel_id=bot.id,
                        user_id=user.id,
                        target=f"dm:{user.email}",
                        message=message.to_dict(),
                    )
                )
        return created

    async def _broadcast(self, channel: Channel, message: Message) -> Delivery:
        if channel.kind == "slack":
            target = str(channel.config.get("channel") or "incoming webhook")
            kind = "slack"
        elif channel.kind == "email":
            target = ", ".join(channel.config.get("to") or [])
            kind = "email"
        else:
            target = urlsplit(str(channel.config.get("url") or "")).netloc
            kind = "webhook"
        return await self._repos.deliveries.add(
            event_type=message.event_type,
            channel=kind,
            channel_id=channel.id,
            user_id=None,
            target=target,
            message=message.to_dict(),
        )
