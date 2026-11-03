"""The bell, personal preferences, org defaults and org channels.

Everyone manages their own inbox and preferences. Org channels and defaults need ``notifications:write`` (Owners and
Administrators hold it through their org role); changes are audited, secrets never echoed back.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_kernel.events import EventBus, RealtimeEvent, user_channel
from agnostic_notifications.application.deliver import Deliver, DeliveryError
from agnostic_notifications.application.ports import Delivery, InboxItem, NewChannel, Repositories
from agnostic_notifications.domain.catalog import (
    EVENT_TYPES,
    ChannelKind,
    EventType,
    QuietHours,
    UnknownEventTypeError,
    event_type,
    valid_channels,
)
from agnostic_notifications.domain.channels import Channel, InvalidChannelError, validate_config, validate_events
from agnostic_notifications.domain.messages import Message

MANAGE = "notifications:write"


class Inbox:
    def __init__(self, repositories: Repositories, bus: EventBus) -> None:
        self._repos = repositories
        self._bus = bus

    async def page(
        self, principal: Principal, *, limit: int, before: tuple[datetime, str] | None, unread_only: bool
    ) -> list[InboxItem]:
        return await self._repos.inbox.page(principal.id, limit=limit, before=before, unread_only=unread_only)

    async def unread(self, principal: Principal) -> int:
        return await self._repos.inbox.unread(principal.id)

    async def mark_read(self, principal: Principal, item_ids: Sequence[str] | None) -> int:
        changed = await self._repos.inbox.mark_read(principal.id, item_ids)
        await self._repos.commit()
        if changed:
            await self._bus.publish(
                user_channel(principal.id),
                RealtimeEvent("notification.read", {"unread": await self._repos.inbox.unread(principal.id)}),
            )
        return changed


@dataclass(frozen=True, slots=True)
class EventPreference:
    event: EventType
    channels: tuple[str, ...]
    """What reaches the person now."""
    custom: bool
    """Their own choice rather than the org default."""


@dataclass(frozen=True, slots=True)
class MyPreferences:
    events: list[EventPreference]
    quiet_hours: QuietHours | None
    slack_available: bool
    """An enabled Slack bot may DM people (otherwise the Slack toggle has no effect)."""


def _quiet(value: Mapping[str, Any] | None) -> QuietHours | None:
    if value is None:
        return None
    try:
        start = time.fromisoformat(str(value["start"]))
        end = time.fromisoformat(str(value["end"]))
        zone = str(value.get("timezone") or "UTC")
        _ = ZoneInfo(zone)
    except (KeyError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValidationFailedError("quiet_hours needs start and end (HH:MM) and an IANA timezone.") from exc
    return QuietHours(start=start, end=end, timezone=zone)


def _channels(event: str, channels: Sequence[str] | None) -> tuple[str, ...] | None:
    try:
        _ = event_type(event)
        return None if channels is None else valid_channels(channels)
    except (UnknownEventTypeError, ValueError) as exc:
        raise ValidationFailedError(str(exc)) from exc


class Preferences:
    def __init__(self, repositories: Repositories, authorizer: Authorizer, audit: AuditLog) -> None:
        self._repos = repositories
        self._authorizer = authorizer
        self._audit = audit

    async def mine(self, principal: Principal) -> MyPreferences:
        chosen = await self._repos.preferences.for_user(principal.id)
        defaults = await self._repos.preferences.defaults()
        events = [
            EventPreference(
                event=event,
                channels=chosen.get(event.name, defaults.get(event.name, event.defaults)),
                custom=event.name in chosen,
            )
            for event in EVENT_TYPES
        ]
        channels = await self._repos.channels.list()
        return MyPreferences(
            events=events,
            quiet_hours=await self._repos.preferences.quiet_hours(principal.id),
            slack_available=any(channel.enabled and channel.sends_direct_messages for channel in channels),
        )

    async def update_mine(
        self,
        principal: Principal,
        events: Mapping[str, Sequence[str] | None],
        *,
        quiet_hours: Mapping[str, Any] | None = None,
        clear_quiet_hours: bool = False,
    ) -> MyPreferences:
        changes = {event: _channels(event, channels) for event, channels in events.items()}
        await self._repos.preferences.set_for_user(principal.id, changes)
        if clear_quiet_hours:
            await self._repos.preferences.set_quiet_hours(principal.id, None)
        elif quiet_hours is not None:
            await self._repos.preferences.set_quiet_hours(principal.id, _quiet(quiet_hours))
        await self._repos.commit()
        return await self.mine(principal)

    async def defaults(self, principal: Principal) -> dict[str, tuple[str, ...]]:
        _ = await self._authorizer.require(principal, MANAGE)
        stored = await self._repos.preferences.defaults()
        return {event.name: stored.get(event.name, event.defaults) for event in EVENT_TYPES}

    async def update_defaults(
        self, principal: Principal, defaults: Mapping[str, Sequence[str] | None]
    ) -> dict[str, tuple[str, ...]]:
        _ = await self._authorizer.require(principal, MANAGE)
        before = await self.defaults(principal)
        changes = {event: _channels(event, channels) for event, channels in defaults.items()}
        await self._repos.preferences.set_defaults(changes)
        after = await self.defaults(principal)
        _ = await self._audit.record(
            AuditEntry(
                action="notifications.defaults.updated",
                actor=actor_of(principal),
                resource_kind="notification_defaults",
                resource_id="org",
                resource_display="Notification defaults",
                scope_checked=MANAGE,
                fields={"events": ", ".join(sorted(changes)) or "nothing"},
                diff={
                    name: {"before": list(before[name]), "after": list(after[name])}
                    for name in changes
                    if before[name] != after[name]
                },
            )
        )
        await self._repos.commit()
        return after


@dataclass(frozen=True, slots=True)
class ChannelView:
    channel: Channel
    recent: list[Delivery]


@dataclass(frozen=True, slots=True)
class ChannelDraft:
    kind: ChannelKind
    name: str
    config: Mapping[str, Any]
    events: Sequence[str] = ()
    instance_ids: Sequence[str] = ()
    enabled: bool = True


class Channels:
    def __init__(self, repositories: Repositories, authorizer: Authorizer, audit: AuditLog, deliver: Deliver) -> None:
        self._repos = repositories
        self._authorizer = authorizer
        self._audit = audit
        self._deliver = deliver

    async def list(self, principal: Principal) -> list[ChannelView]:
        _ = await self._authorizer.require(principal, MANAGE)
        return [
            ChannelView(channel, await self._repos.deliveries.recent(channel_id=channel.id, limit=5))
            for channel in await self._repos.channels.list()
        ]

    async def get(self, principal: Principal, channel_id: str) -> ChannelView:
        _ = await self._authorizer.require(principal, MANAGE)
        channel = await self._existing(channel_id)
        return ChannelView(channel, await self._repos.deliveries.recent(channel_id=channel.id, limit=20))

    async def _existing(self, channel_id: str) -> Channel:
        channel = await self._repos.channels.get(channel_id)
        if channel is None:
            raise NotFoundError(f"There is no notification channel {channel_id!r}.")
        return channel

    async def create(self, principal: Principal, draft: ChannelDraft) -> Channel:
        _ = await self._authorizer.require(principal, MANAGE)
        name = draft.name.strip()
        if not name:
            raise ValidationFailedError("A channel needs a name.")
        try:
            config = validate_config(draft.kind, draft.config)
            events = validate_events(draft.events)
        except InvalidChannelError as exc:
            raise ValidationFailedError(str(exc)) from exc
        channel = await self._repos.channels.add(
            NewChannel(draft.kind, name, config, events, tuple(draft.instance_ids), draft.enabled),
            created_by=principal.id,
        )
        await self._record(principal, "notifications.channel.created", channel)
        await self._repos.commit()
        return channel

    async def update(self, principal: Principal, channel_id: str, changes: Mapping[str, Any]) -> Channel:
        _ = await self._authorizer.require(principal, MANAGE)
        current = await self._existing(channel_id)
        values: dict[str, Any] = {}
        try:
            if "name" in changes:
                values["name"] = str(changes["name"]).strip() or current.name
            if "config" in changes:
                values["config"] = validate_config(current.kind, changes["config"], current.config)
            if "events" in changes:
                values["events"] = validate_events(changes["events"])
        except InvalidChannelError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if "instance_ids" in changes:
            values["instance_ids"] = tuple(changes["instance_ids"])
        if "enabled" in changes:
            values["enabled"] = bool(changes["enabled"])
        channel = await self._repos.channels.update(channel_id, values)
        await self._record(principal, "notifications.channel.updated", channel, changed=sorted(values))
        await self._repos.commit()
        return channel

    async def delete(self, principal: Principal, channel_id: str) -> None:
        _ = await self._authorizer.require(principal, MANAGE)
        channel = await self._existing(channel_id)
        await self._repos.channels.delete(channel_id)
        await self._record(principal, "notifications.channel.deleted", channel)
        await self._repos.commit()

    async def test(self, principal: Principal, channel_id: str) -> Delivery:
        """Sends a test message right away (not through the job queue) and returns the recorded outcome."""
        _ = await self._authorizer.require(principal, MANAGE)
        channel = await self._existing(channel_id)
        kind = "webhook" if channel.kind == "webhook" else channel.kind
        message = Message(
            event_type="test",
            title=f"Test notification from Agnostic ({channel.name})",
            body=f"{principal.display_name} sent this to check the channel.",
        )
        target = str(channel.config.get("channel") or ", ".join(channel.config.get("to") or []) or channel.name)
        delivery = await self._repos.deliveries.add(
            event_type="test",
            channel=kind,
            channel_id=channel.id,
            user_id=principal.id,
            target=target,
            message=message.to_dict(),
        )
        await self._repos.commit()
        with contextlib.suppress(DeliveryError):  # recorded as failed by the last attempt
            await self._deliver(delivery.id, last_attempt=True)
        result = await self._repos.deliveries.get(delivery.id)
        assert result is not None
        return result

    async def _record(
        self, principal: Principal, action: str, channel: Channel, *, changed: list[str] | None = None
    ) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="notification_channel",
                resource_id=channel.id,
                resource_display=channel.name,
                scope_checked=MANAGE,
                fields={"channel": channel.name, "kind": channel.kind},
                diff={"changed": changed} if changed else None,
            )
        )
