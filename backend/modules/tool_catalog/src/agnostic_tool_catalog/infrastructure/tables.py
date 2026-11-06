"""Tables owned by the tool catalog module (``tcat_*``). None holds a secret: credentials are env var names."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class ToolCatalogBase(DeclarativeBase):
    metadata = make_metadata()


class EntryRow(TimestampMixin, ToolCatalogBase):
    __tablename__ = "tcat_entries"
    __table_args__ = (Index("ix_tcat_entries_level", "level", "owner_group_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    slug: Mapped[str] = mapped_column(String(40))
    registry_name: Mapped[str] = mapped_column(String(63), unique=True)
    level: Mapped[str] = mapped_column(String(10))
    owner_group_id: Mapped[str | None] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str | None] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(10))
    transport: Mapped[str | None] = mapped_column(String(20))
    toolkit_key: Mapped[str | None] = mapped_column(String(80))
    config: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    requires_confirmation_tools: Mapped[list[str]] = mapped_column(JsonDocument)
    local: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(40))


class EntryInstanceRow(ToolCatalogBase):
    """Limits an entry to some instances; an entry without rows applies to every instance."""

    __tablename__ = "tcat_entry_instances"

    entry_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)


class SyncStateRow(ToolCatalogBase):
    """The last time each instance's bridge pulled its manifest."""

    __tablename__ = "tcat_sync_state"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    manifest_etag: Mapped[str | None] = mapped_column(String(80))
    entries: Mapped[int] = mapped_column(Integer, default=0)
    bridge_version: Mapped[str | None] = mapped_column(String(40))
    last_pull_ip: Mapped[str | None] = mapped_column(String(64))
    last_pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
