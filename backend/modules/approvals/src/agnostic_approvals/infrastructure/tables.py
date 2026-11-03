"""Tables owned by the approvals module (``apr_*``). Approvals themselves stay in AgentOS (``agno_approvals``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class ApprovalsBase(DeclarativeBase):
    metadata = make_metadata()


class RouteRow(TimestampMixin, ApprovalsBase):
    __tablename__ = "apr_routes"
    __table_args__ = (Index("ix_apr_routes_instance_id", "instance_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str | None] = mapped_column(String(40))
    """``None``: applies on every instance that has no matching rule of its own."""
    name: Mapped[str] = mapped_column(String(200))
    tool_name: Mapped[str | None] = mapped_column(String(200))
    component_kind: Mapped[str | None] = mapped_column(String(20))
    component_ids: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    member_ids: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    role_ids: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    channels: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    channel_ids: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    created_by: Mapped[str | None] = mapped_column(String(40))


class ViewRow(ApprovalsBase):
    __tablename__ = "apr_views"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventRow(ApprovalsBase):
    __tablename__ = "apr_events"
    __table_args__ = (Index("ix_apr_events_approval", "instance_id", "approval_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(40))
    approval_id: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    actor: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyRow(ApprovalsBase):
    __tablename__ = "apr_policies"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    enforce_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    ttl_hours: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
