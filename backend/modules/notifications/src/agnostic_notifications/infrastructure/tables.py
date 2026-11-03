"""Tables owned by the notifications module (``ntf_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class NotificationsBase(DeclarativeBase):
    metadata = make_metadata()


class ChannelRow(TimestampMixin, NotificationsBase):
    __tablename__ = "ntf_channels"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    config_enc: Mapped[str] = mapped_column(Text)
    """The channel config (tokens, webhook URLs, secrets included) sealed with the instance master key."""
    events: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    instance_ids: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(40))


class DefaultRow(NotificationsBase):
    """Org default personal channels per event type."""

    __tablename__ = "ntf_defaults"

    event_type: Mapped[str] = mapped_column(String(60), primary_key=True)
    channels: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PreferenceRow(NotificationsBase):
    __tablename__ = "ntf_preferences"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60), primary_key=True)
    channels: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuietHoursRow(NotificationsBase):
    __tablename__ = "ntf_quiet_hours"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(64))


class InboxRow(NotificationsBase):
    __tablename__ = "ntf_inbox"
    __table_args__ = (Index("ix_ntf_inbox_user_id", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(1000))
    instance_id: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryRow(NotificationsBase):
    __tablename__ = "ntf_deliveries"
    __table_args__ = (Index("ix_ntf_deliveries_channel_id", "channel_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(20))
    channel_id: Mapped[str | None] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(500))
    message: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    message_ref: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
