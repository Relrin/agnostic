"""Tables owned by the service_accounts module (``sa_*``). Native token hashes stay in AgentOS."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class ServiceAccountsBase(DeclarativeBase):
    metadata = make_metadata()


class AccountRow(ServiceAccountsBase):
    __tablename__ = "sa_accounts"
    __table_args__ = (
        Index(
            "uq_sa_accounts_name_live",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(63))
    principal: Mapped[str] = mapped_column(String(70))
    description: Mapped[str] = mapped_column(Text, default="")
    scope_source: Mapped[str] = mapped_column(String(10))
    role_id: Mapped[str | None] = mapped_column(String(40))
    scopes: Mapped[list[str]] = mapped_column(JsonDocument)
    instance_ids: Mapped[list[str]] = mapped_column(JsonDocument)
    forwards_user_id: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(40))
    created_by_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InstanceTokenRow(ServiceAccountsBase):
    """Native ``agno_pat_`` tokens, one active per account and instance."""

    __tablename__ = "sa_instance_tokens"
    __table_args__ = (
        Index("ix_sa_instance_tokens_sa_id", "sa_id"),
        Index("ix_sa_instance_tokens_instance_id_status", "instance_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    sa_id: Mapped[str] = mapped_column(String(40))
    instance_id: Mapped[str] = mapped_column(String(40))
    agentos_sa_id: Mapped[str] = mapped_column(String(200))
    token_prefix: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    scopes: Mapped[list[str]] = mapped_column(JsonDocument)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GatewayTokenRow(ServiceAccountsBase):
    """Gateway ``agn_pat_`` tokens: sha256 of the pepper and the token, never the token."""

    __tablename__ = "sa_gateway_tokens"
    __table_args__ = (Index("ix_sa_gateway_tokens_sa_id", "sa_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    sa_id: Mapped[str] = mapped_column(String(40))
    prefix: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(200))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(String(64))
