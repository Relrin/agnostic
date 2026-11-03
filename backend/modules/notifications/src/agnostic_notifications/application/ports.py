"""What the notifications use cases need from storage and the outside world."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from agnostic_notifications.domain.catalog import ChannelKind, QuietHours
from agnostic_notifications.domain.channels import Channel

type DeliveryStatus = Literal["pending", "sent", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class InboxItem:
    id: str
    user_id: str
    kind: str
    title: str
    body: str
    link: str | None
    instance_id: str | None
    payload: Mapping[str, Any]
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    event_type: str
    channel: Literal["email", "slack", "slack_dm", "webhook"]
    channel_id: str | None
    user_id: str | None
    target: str
    """An email address, a Slack channel, ``dm:<email>``, a webhook host: what people see in the log."""
    message: Mapping[str, Any]
    status: DeliveryStatus
    attempts: int
    error: str | None
    message_ref: str | None
    created_at: datetime
    sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewChannel:
    kind: ChannelKind
    name: str
    config: Mapping[str, Any]
    events: tuple[str, ...]
    instance_ids: tuple[str, ...]
    enabled: bool


class ChannelRepository(Protocol):
    async def list(self) -> list[Channel]: ...
    async def get(self, channel_id: str) -> Channel | None: ...
    async def add(self, channel: NewChannel, *, created_by: str) -> Channel: ...
    async def update(self, channel_id: str, changes: Mapping[str, Any]) -> Channel: ...
    async def delete(self, channel_id: str) -> None: ...


class PreferenceRepository(Protocol):
    async def for_user(self, user_id: str) -> dict[str, tuple[str, ...]]: ...
    async def set_for_user(self, user_id: str, preferences: Mapping[str, Sequence[str] | None]) -> None:
        """``None`` removes the person's choice for that event (the org default applies again)."""
        ...

    async def defaults(self) -> dict[str, tuple[str, ...]]: ...
    async def set_defaults(self, defaults: Mapping[str, Sequence[str] | None]) -> None: ...
    async def quiet_hours(self, user_id: str) -> QuietHours | None: ...
    async def set_quiet_hours(self, user_id: str, quiet: QuietHours | None) -> None: ...


class InboxRepository(Protocol):
    async def add(
        self,
        *,
        user_id: str,
        kind: str,
        title: str,
        body: str,
        link: str | None,
        instance_id: str | None,
        payload: Mapping[str, Any],
    ) -> InboxItem: ...
    async def page(
        self, user_id: str, *, limit: int, before: tuple[datetime, str] | None, unread_only: bool
    ) -> list[InboxItem]: ...
    async def unread(self, user_id: str) -> int: ...
    async def mark_read(self, user_id: str, item_ids: Sequence[str] | None) -> int:
        """Marks the given items (or all, with ``None``) read; returns how many changed."""
        ...


class DeliveryRepository(Protocol):
    async def add(
        self,
        *,
        event_type: str,
        channel: str,
        channel_id: str | None,
        user_id: str | None,
        target: str,
        message: Mapping[str, Any],
    ) -> Delivery: ...
    async def get(self, delivery_id: str) -> Delivery | None: ...
    async def finish(
        self, delivery_id: str, *, status: DeliveryStatus, error: str | None = None, message_ref: str | None = None
    ) -> None: ...
    async def recent(self, *, channel_id: str | None = None, limit: int = 20) -> list[Delivery]: ...


class Repositories(Protocol):
    @property
    def channels(self) -> ChannelRepository: ...
    @property
    def preferences(self) -> PreferenceRepository: ...
    @property
    def inbox(self) -> InboxRepository: ...
    @property
    def deliveries(self) -> DeliveryRepository: ...

    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboundResponse:
    status: int
    body: Any


class OutboundHttp(Protocol):
    """HTTP to Slack and webhooks (tests swap in fakes)."""

    async def post(
        self,
        url: str,
        *,
        json: Any = None,  # noqa: ANN401
        content: bytes | None = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> OutboundResponse: ...
