"""Tables owned by the identity module (``identity_*``).

Emails are stored lowercased, so a plain unique index works on both PostgreSQL and SQLite.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
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


SINGLE_CREDENTIAL_KINDS = "kind IN ('password', 'totp')"


class CredentialRow(IdentityBase):
    """Passwords and second factors.

    One password and one authenticator app per person; any number of security keys and recovery codes.
    """

    __tablename__ = "identity_credentials"
    __table_args__ = (
        Index(
            "uq_identity_credentials_user_id_single_kind",
            "user_id",
            "kind",
            unique=True,
            postgresql_where=text(SINGLE_CREDENTIAL_KINDS),
            sqlite_where=text(SINGLE_CREDENTIAL_KINDS),
        ),
        Index("ix_identity_credentials_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("identity_users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    """``password``, ``totp``, ``webauthn`` or ``recovery``."""
    secret_hash: Mapped[str] = mapped_column(Text)
    """password: argon2id hash; totp: the sealed secret; webauthn: the credential id (base64url); recovery: sha256."""
    label: Mapped[str | None] = mapped_column(String(120))
    data: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    """webauthn: the public key, transports and AAGUID."""
    sign_count: Mapped[int | None] = mapped_column(Integer)
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
    value: Mapped[Any] = mapped_column(JsonDocument, nullable=True)


class LoginProviderRow(IdentityBase):
    """Sign-in providers managed in the app (settings-configured ones aren't stored)."""

    __tablename__ = "identity_login_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(120))
    preset: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    """Protocol settings; secrets inside are sealed with the master key (``SecretBox``)."""
    allowed_email_domains: Mapped[list[str]] = mapped_column(JsonDocument)
    jit_provisioning: Mapped[bool] = mapped_column(Boolean)
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthPolicyRow(IdentityBase):
    """The org's authentication policy: a single row (``id = 1``)."""

    __tablename__ = "identity_auth_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enforce_sso: Mapped[bool] = mapped_column(Boolean)
    break_glass_user_id: Mapped[str | None] = mapped_column(String(40))
    session_idle_minutes: Mapped[int | None] = mapped_column(Integer)
    session_absolute_hours: Mapped[int | None] = mapped_column(Integer)
    mfa_policy: Mapped[str] = mapped_column(String(20))
    updated_by: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
