"""Tables owned by the access module (``access_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class AccessBase(DeclarativeBase):
    metadata = make_metadata()


class ScopeCatalogRow(AccessBase):
    __tablename__ = "access_scope_catalog"

    scope: Mapped[str] = mapped_column(String(120), primary_key=True)
    family: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    resource_kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    agentos_min_version: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    privileged: Mapped[bool] = mapped_column(Boolean)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)


class RoleRow(AccessBase):
    __tablename__ = "access_roles"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(20))
    permissions: Mapped[dict[str, list[str]]] = mapped_column(JsonDocument)
    run_scope: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    bindable_instance_ids: Mapped[list[str] | None] = mapped_column(JsonDocument)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BindingRow(AccessBase):
    __tablename__ = "access_bindings"
    __table_args__ = (
        Index("ix_access_bindings_principal_kind_principal_id", "principal_kind", "principal_id"),
        Index("ix_access_bindings_instance_id", "instance_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    principal_kind: Mapped[str] = mapped_column(String(20))
    principal_id: Mapped[str] = mapped_column(String(200))
    instance_id: Mapped[str | None] = mapped_column(String(40))
    role_id: Mapped[str | None] = mapped_column(String(40))
    scopes: Mapped[list[str]] = mapped_column(JsonDocument)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
