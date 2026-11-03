"""Tables owned by the directory module (``dir_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class DirectoryBase(DeclarativeBase):
    metadata = make_metadata()


class GroupRow(DirectoryBase):
    __tablename__ = "dir_groups"
    __table_args__ = (Index("ix_dir_groups_source_external_id", "source", "external_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str | None] = mapped_column(String(200))
    external_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupMemberRow(DirectoryBase):
    __tablename__ = "dir_group_members"
    __table_args__ = (Index("ix_dir_group_members_user_id", "user_id"),)

    group_id: Mapped[str] = mapped_column(String(40), ForeignKey("dir_groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default="member")
    source: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[str | None] = mapped_column(String(40))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScimTokenRow(DirectoryBase):
    __tablename__ = "dir_scim_tokens"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_from: Mapped[str | None] = mapped_column(String(40))


class ScimSyncStateRow(DirectoryBase):
    """A single row (``id = 1``)."""

    __tablename__ = "dir_scim_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[dict[str, int]] = mapped_column(JsonDocument, default=dict)


class ScimUserRow(DirectoryBase):
    """What the IdP knows about a person: its id for them, their userName and the resource as last sent."""

    __tablename__ = "dir_scim_users"
    __table_args__ = (Index("ix_dir_scim_users_external_id", "external_id"),)

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    user_name: Mapped[str] = mapped_column(String(320))
    user_name_key: Mapped[str] = mapped_column(String(320), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MappingRuleRow(DirectoryBase):
    __tablename__ = "dir_mapping_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    idp_group: Mapped[str] = mapped_column(String(200))
    group_id: Mapped[str] = mapped_column(String(40), ForeignKey("dir_groups.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoogleSyncRow(DirectoryBase):
    """A single row (``id = 1``); ``config_enc`` is the sealed service-account key and admin subject."""

    __tablename__ = "dir_google_sync"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_enc: Mapped[str | None] = mapped_column(Text)
    group_filter: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    counts: Mapped[dict[str, int]] = mapped_column(JsonDocument, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DirectorySettingsRow(DirectoryBase):
    """A single row (``id = 1``)."""

    __tablename__ = "dir_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deprovision: Mapped[str] = mapped_column(String(10), default="disable")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
