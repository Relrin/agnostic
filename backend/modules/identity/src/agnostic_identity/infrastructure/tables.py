"""Tables owned by the identity module (``identity_*``).

Emails are stored lowercased, so a plain unique index works on both PostgreSQL and SQLite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class IdentityBase(DeclarativeBase):
    metadata = make_metadata()


class UserRow(IdentityBase):
    __tablename__ = "identity_users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    avatar_seed: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    locale: Mapped[str | None] = mapped_column(String(35))
    timezone: Mapped[str | None] = mapped_column(String(64))
    created_via: Mapped[str] = mapped_column(String(20))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CredentialRow(IdentityBase):
    __tablename__ = "identity_credentials"
    __table_args__ = (UniqueConstraint("user_id", "kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    secret_hash: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalIdentityRow(IdentityBase):
    __tablename__ = "identity_external_identities"
    __table_args__ = (UniqueConstraint("provider_id", "subject"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(255))
    email_at_provider: Mapped[str | None] = mapped_column(String(320))
    raw_claims: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRecordRow(IdentityBase):
    """Audit copy of web sessions; the live session is in the ephemeral store."""

    __tablename__ = "identity_sessions"
    __table_args__ = (Index("ix_identity_sessions_user_id_revoked_at", "user_id", "revoked_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(80))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PreferenceRow(IdentityBase):
    __tablename__ = "identity_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonDocument)
