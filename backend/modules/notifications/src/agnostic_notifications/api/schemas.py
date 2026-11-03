"""Request and response bodies of the notifications API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_notifications.application.manage import ChannelView, MyPreferences
from agnostic_notifications.application.ports import Delivery, InboxItem
from agnostic_notifications.domain.catalog import EVENT_TYPES, QuietHours

type PersonalChannelName = Literal["in_app", "email", "slack"]
type ChannelKindName = Literal["slack", "email", "webhook"]


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    link: str | None
    instance_id: str | None
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None

    @classmethod
    def of(cls, item: InboxItem) -> NotificationOut:
        return cls(
            id=item.id,
            kind=item.kind,
            title=item.title,
            body=item.body,
            link=item.link,
            instance_id=item.instance_id,
            data=dict(item.payload),
            created_at=item.created_at,
            read_at=item.read_at,
        )


class UnreadOut(BaseModel):
    unread: int


class MarkReadIn(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=500, description="Leave out to mark everything read")


class MarkReadOut(BaseModel):
    changed: int
    unread: int


class EventTypeOut(BaseModel):
    name: str
    label: str
    description: str
    defaults: list[PersonalChannelName]


def catalog() -> list[EventTypeOut]:
    return [
        EventTypeOut(name=e.name, label=e.label, description=e.description, defaults=list(e.defaults))
        for e in EVENT_TYPES
    ]


class QuietHoursBody(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$", examples=["22:00"])
    end: str = Field(pattern=r"^\d{2}:\d{2}$", examples=["07:00"])
    timezone: str = Field(default="UTC", max_length=64)

    @classmethod
    def of(cls, quiet: QuietHours | None) -> QuietHoursBody | None:
        if quiet is None:
            return None
        return cls(start=quiet.start.strftime("%H:%M"), end=quiet.end.strftime("%H:%M"), timezone=quiet.timezone)


class EventPreferenceOut(BaseModel):
    event: EventTypeOut
    channels: list[PersonalChannelName]
    custom: bool


class PreferencesOut(BaseModel):
    events: list[EventPreferenceOut]
    quiet_hours: QuietHoursBody | None
    slack_available: bool

    @classmethod
    def of(cls, value: MyPreferences) -> PreferencesOut:
        return cls(
            events=[
                EventPreferenceOut(
                    event=EventTypeOut(
                        name=p.event.name,
                        label=p.event.label,
                        description=p.event.description,
                        defaults=list(p.event.defaults),
                    ),
                    channels=list(p.channels),  # pyright: ignore[reportArgumentType]
                    custom=p.custom,
                )
                for p in value.events
            ],
            quiet_hours=QuietHoursBody.of(value.quiet_hours),
            slack_available=value.slack_available,
        )


class PreferencesIn(BaseModel):
    events: dict[str, list[PersonalChannelName] | None] = Field(
        default_factory=dict, description="Event type → channels; null goes back to the org default"
    )
    quiet_hours: QuietHoursBody | None = None
    clear_quiet_hours: bool = False


class DefaultsBody(BaseModel):
    events: dict[str, list[PersonalChannelName] | None]


class DeliveryOut(BaseModel):
    id: str
    event_type: str
    channel: str
    target: str
    status: Literal["pending", "sent", "failed", "skipped"]
    attempts: int
    error: str | None
    created_at: datetime
    sent_at: datetime | None

    @classmethod
    def of(cls, delivery: Delivery) -> DeliveryOut:
        return cls(
            id=delivery.id,
            event_type=delivery.event_type,
            channel=delivery.channel,
            target=delivery.target,
            status=delivery.status,
            attempts=delivery.attempts,
            error=delivery.error,
            created_at=delivery.created_at,
            sent_at=delivery.sent_at,
        )


class ChannelOut(BaseModel):
    id: str
    kind: ChannelKindName
    name: str
    config: dict[str, Any] = Field(description="Secrets are shown as their last characters, never in full")
    events: list[str]
    instance_ids: list[str]
    enabled: bool
    sends_direct_messages: bool
    created_at: datetime
    updated_at: datetime
    recent: list[DeliveryOut]

    @classmethod
    def of(cls, view: ChannelView) -> ChannelOut:
        channel = view.channel
        return cls(
            id=channel.id,
            kind=channel.kind,
            name=channel.name,
            config=channel.public_config(),
            events=list(channel.events),
            instance_ids=list(channel.instance_ids),
            enabled=channel.enabled,
            sends_direct_messages=channel.sends_direct_messages,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
            recent=[DeliveryOut.of(d) for d in view.recent],
        )


class ChannelIn(BaseModel):
    kind: ChannelKindName
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(
        description=(
            "slack: {mode: bot|webhook, token?, channel?, direct_messages?, webhook_url?, api_base?}; "
            "email: {to: [addresses]}; webhook: {url, secret?}"
        )
    )
    events: list[str] = Field(default_factory=list, description="Event types posted here for everyone")
    instance_ids: list[str] = Field(default_factory=list, description="Empty: every instance")
    enabled: bool = True


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] | None = Field(default=None, description="Secrets left out keep their current value")
    events: list[str] | None = None
    instance_ids: list[str] | None = None
    enabled: bool | None = None
