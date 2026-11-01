"""Tables owned by the audit module.

On PostgreSQL ``audit_events`` is range-partitioned by month (see the migration); the model below describes the
parent table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class AuditBase(DeclarativeBase):
    metadata = make_metadata()


class AuditEventRow(AuditBase):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_actor_id_occurred_at", "actor_id", "occurred_at"),
        Index("ix_audit_events_action_occurred_at", "action", "occurred_at"),
        Index("ix_audit_events_instance_id_occurred_at", "instance_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String(160))
    actor_kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(200))
    actor_display: Mapped[str] = mapped_column(String(320))
    via: Mapped[str] = mapped_column(String(40))
    ip: Mapped[str | None] = mapped_column(String(64))
    client: Mapped[str | None] = mapped_column(String(512))
    action: Mapped[str] = mapped_column(String(120))
    resource_kind: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(200))
    resource_display: Mapped[str | None] = mapped_column(Text)
    instance_id: Mapped[str | None] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(10))
    scope_checked: Mapped[str | None] = mapped_column(String(200))
    missing_scopes: Mapped[list[str] | None] = mapped_column(JsonDocument)
    response_status: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    links: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    source: Mapped[str] = mapped_column(String(20))
    source_event_id: Mapped[str | None] = mapped_column(String(200))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str | None] = mapped_column(String(64))
