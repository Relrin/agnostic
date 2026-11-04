"""Tables owned by the instances module (``inst_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class InstancesBase(DeclarativeBase):
    metadata = make_metadata()


class InstanceRow(InstancesBase):
    __tablename__ = "inst_instances"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    env_tag: Mapped[str] = mapped_column(String(20))
    endpoint_url: Mapped[str] = mapped_column(String(2048))
    network_mode: Mapped[str] = mapped_column(String(20), default="gateway")
    os_id: Mapped[str | None] = mapped_column(String(200))
    agno_version: Mapped[str | None] = mapped_column(String(40))
    os_version: Mapped[str | None] = mapped_column(String(40))
    auth_mode: Mapped[str] = mapped_column(String(20))
    user_isolation: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    sub_claim_mode: Mapped[str] = mapped_column(String(20))
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_bundle_pem: Mapped[str | None] = mapped_column(Text)
    security_key_enc: Mapped[str | None] = mapped_column(Text)
    client_cert_pem: Mapped[str | None] = mapped_column(Text)
    client_key_enc: Mapped[str | None] = mapped_column(Text)
    browser_url: Mapped[str | None] = mapped_column(String(2048))
    previous_agno_version: Mapped[str | None] = mapped_column(String(40))
    version_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1)
    elevation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SnapshotRow(InstancesBase):
    __tablename__ = "inst_snapshots"
    __table_args__ = (Index("ix_inst_snapshots_instance_id_kind_fetched_at", "instance_id", "kind", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(ForeignKey("inst_instances.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[Any] = mapped_column(JsonDocument, nullable=True)
    hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CapabilityRow(InstancesBase):
    __tablename__ = "inst_capabilities"

    instance_id: Mapped[str] = mapped_column(ForeignKey("inst_instances.id", ondelete="CASCADE"), primary_key=True)
    capability: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JwtKeyRow(InstancesBase):
    __tablename__ = "inst_jwt_keys"

    instance_id: Mapped[str] = mapped_column(ForeignKey("inst_instances.id", ondelete="CASCADE"), primary_key=True)
    kid: Mapped[str] = mapped_column(String(64), primary_key=True)
    alg: Mapped[str] = mapped_column(String(10))
    public_pem: Mapped[str] = mapped_column(Text)
    private_enc: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
