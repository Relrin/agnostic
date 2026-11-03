"""Tables owned by the studio module (``studio_*``): metadata Studio keeps next to AgentOS components."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, make_metadata


class StudioBase(DeclarativeBase):
    metadata = make_metadata()


class ComponentMetaRow(StudioBase):
    __tablename__ = "studio_component_meta"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    owner_group_id: Mapped[str | None] = mapped_column(String(40))
    labels: Mapped[list[str]] = mapped_column(JsonDocument, default=list)
    last_known_current_version: Mapped[int | None] = mapped_column(Integer)
    source_binding_id: Mapped[str | None] = mapped_column(String(40))
    code_path: Mapped[str | None] = mapped_column(String(500))
    convention: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VersionMetaRow(StudioBase):
    __tablename__ = "studio_version_meta"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[str | None] = mapped_column(String(40))
    author_name: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_by_name: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[str | None] = mapped_column(Text)
    based_on_version: Mapped[int | None] = mapped_column(Integer)
    eval_status: Mapped[str | None] = mapped_column(String(20))
    published_by: Mapped[str | None] = mapped_column(String(40))
    published_by_name: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_from: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)


class RegistryIndexRow(StudioBase):
    __tablename__ = "studio_registry_index"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    entry_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    used_by: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument, default=list)
    studio_available: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CanvasLayoutRow(StudioBase):
    __tablename__ = "studio_canvas_layouts"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    layout: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CodeDocumentRow(StudioBase):
    __tablename__ = "studio_code_documents"

    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text)
    config_hash: Mapped[str] = mapped_column(String(64))
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_by_name: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromotionRow(StudioBase):
    __tablename__ = "studio_promotions"
    __table_args__ = (Index("ix_studio_promotions_component", "from_instance", "component_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    from_instance: Mapped[str] = mapped_column(String(40))
    to_instance: Mapped[str] = mapped_column(String(40))
    component_id: Mapped[str] = mapped_column(String(200))
    component_kind: Mapped[str] = mapped_column(String(20))
    from_version: Mapped[int] = mapped_column(Integer)
    to_version: Mapped[int | None] = mapped_column(Integer)
    include_children: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20))
    report: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    created_by: Mapped[str] = mapped_column(String(40))
    created_by_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
