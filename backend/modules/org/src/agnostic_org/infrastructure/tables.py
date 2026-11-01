"""Tables owned by the org module (``org_*``). ``org_profile`` holds one row: one org per installation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata

PROFILE_ID = "org"


class OrgBase(DeclarativeBase):
    metadata = make_metadata()


class OrgProfileRow(OrgBase):
    __tablename__ = "org_profile"

    id: Mapped[str] = mapped_column(String(8), primary_key=True, default=PROFILE_ID)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(63))
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    plan_label: Mapped[str | None] = mapped_column(String(80))
    seat_limit: Mapped[int | None] = mapped_column(Integer)
    bootstrap_token_hash: Mapped[str | None] = mapped_column(String(64))
    bootstrap_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberRow(OrgBase):
    __tablename__ = "org_members"

    # References identity_users.id (the foreign key lives in the migration: it crosses module metadata).
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    joined_via: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvitationRow(OrgBase):
    __tablename__ = "org_invitations"
    __table_args__ = (Index("ix_org_invitations_email_status", "email", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    org_role: Mapped[str] = mapped_column(String(20))
    bindings: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument)
    access_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[str] = mapped_column(String(40))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
