"""Tables owned by the audit module.

On PostgreSQL ``audit_events`` is range-partitioned by month (see the migration); the model below describes the
parent table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, LargeBinary, String, Text, func
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
        Index("ix_audit_events_resource_id_occurred_at", "resource_id", "occurred_at"),
        Index("ix_audit_events_source_source_event_id", "source", "source_event_id"),
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
    denial_reason: Mapped[str | None] = mapped_column(Text)


class SavedViewRow(AuditBase):
    __tablename__ = "audit_saved_views"
    __table_args__ = (Index("ix_audit_saved_views_owner_id", "owner_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExportRow(AuditBase):
    __tablename__ = "audit_exports"
    __table_args__ = (Index("ix_audit_exports_requested_by_created_at", "requested_by", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    requested_by: Mapped[str] = mapped_column(String(200))
    filters: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    row_count: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    """zstd-compressed CSV or JSONL."""
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyRow(AuditBase):
    """A single row (``id = 1``); absent until someone saves the policy."""

    __tablename__ = "audit_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hot_retention_days: Mapped[int] = mapped_column(Integer, default=400)
    archive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    endpoint: Mapped[str | None] = mapped_column(String(512))
    bucket: Mapped[str | None] = mapped_column(String(255))
    prefix: Mapped[str] = mapped_column(String(512), default="")
    region: Mapped[str] = mapped_column(String(64), default="us-east-1")
    access_key_id: Mapped[str | None] = mapped_column(String(255))
    secret_enc: Mapped[str | None] = mapped_column(Text)
    object_lock_mode: Mapped[str] = mapped_column(String(12), default="off")
    archive_retention_days: Mapped[int | None] = mapped_column(Integer)
    hash_chain: Mapped[bool] = mapped_column(Boolean, default=False)
    last_archive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_archive_error: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArchiveRow(AuditBase):
    __tablename__ = "audit_archives"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    object_key: Mapped[str] = mapped_column(String(1024))
    manifest_key: Mapped[str] = mapped_column(String(1024))
    bytes: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    chain_head: Mapped[str | None] = mapped_column(String(64))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SinkRow(AuditBase):
    __tablename__ = "audit_sinks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    format: Mapped[str] = mapped_column(String(10))
    config_enc: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(10), default="ok")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SinkCursorRow(AuditBase):
    __tablename__ = "audit_sink_cursors"

    sink_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[str] = mapped_column(String(40))


class IngestCursorRow(AuditBase):
    __tablename__ = "audit_ingest_cursors"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    stream: Mapped[str] = mapped_column(String(20), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(200))
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
