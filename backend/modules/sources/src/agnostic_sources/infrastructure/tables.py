"""Tables owned by the sources module (``src_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class SourcesBase(DeclarativeBase):
    metadata = make_metadata()


class ConnectionRow(TimestampMixin, SourcesBase):
    __tablename__ = "src_connections"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(20))
    auth_kind: Mapped[str] = mapped_column(String(20))
    access: Mapped[str] = mapped_column(String(20))
    api_url: Mapped[str | None] = mapped_column(String(500))
    web_url: Mapped[str | None] = mapped_column(String(500))
    app_slug: Mapped[str | None] = mapped_column(String(200))
    installation_id: Mapped[str | None] = mapped_column(String(40))
    account: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_enc: Mapped[str | None] = mapped_column(Text)
    """App id, private key, token or deploy key, sealed with the master key."""
    created_by: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)


class SourceRow(TimestampMixin, SourcesBase):
    __tablename__ = "src_sources"
    __table_args__ = (Index("ix_src_sources_instance", "instance_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(40))
    connection_id: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))
    repo: Mapped[str] = mapped_column(String(300))
    branch: Mapped[str] = mapped_column(String(200))
    clone_url: Mapped[str | None] = mapped_column(String(500))
    local_path: Mapped[str | None] = mapped_column(String(500))
    convention: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    status: Mapped[str] = mapped_column(String(20))
    status_detail: Mapped[str | None] = mapped_column(Text)
    last_fetched_sha: Mapped[str | None] = mapped_column(String(64))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_report: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    webhook_id: Mapped[str | None] = mapped_column(String(100))
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)


class PathMappingRow(SourcesBase):
    __tablename__ = "src_path_mappings"

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    glob: Mapped[str] = mapped_column(String(500))
    target_kind: Mapped[str] = mapped_column(String(20))
    writable: Mapped[bool] = mapped_column(Boolean, default=True)


class SyncPolicyRow(SourcesBase):
    __tablename__ = "src_sync_policies"

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    pull_mode: Mapped[str] = mapped_column(String(30))
    publish_mode: Mapped[str] = mapped_column(String(30))
    branch_template: Mapped[str] = mapped_column(String(200))
    commit_template: Mapped[str] = mapped_column(String(300))
    block_publish_until_merged: Mapped[bool] = mapped_column(Boolean, default=False)


class FileBindingRow(SourcesBase):
    __tablename__ = "src_file_bindings"
    __table_args__ = (
        UniqueConstraint("source_id", "path", "component_id", name="uq_src_file_bindings_file"),
        Index("ix_src_file_bindings_component", "component_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(String(500))
    component_kind: Mapped[str] = mapped_column(String(20))
    component_id: Mapped[str] = mapped_column(String(200))
    last_synced_sha: Mapped[str | None] = mapped_column(String(64))
    last_synced_version: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    synced_code: Mapped[str | None] = mapped_column(Text)
    synced_config: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChangeRow(TimestampMixin, SourcesBase):
    __tablename__ = "src_changes"
    __table_args__ = (Index("ix_src_changes_source", "source_id", "direction", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(500))
    component_kind: Mapped[str | None] = mapped_column(String(20))
    component_id: Mapped[str | None] = mapped_column(String(200))
    binding_id: Mapped[str | None] = mapped_column(String(40))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    blob: Mapped[str | None] = mapped_column(String(64))
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_email: Mapped[str | None] = mapped_column(String(320))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    before_code: Mapped[str | None] = mapped_column(Text)
    after_code: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    base_config: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    outcome: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument, default=list)
    incoming_marks: Mapped[dict[str, str]] = mapped_column(JsonDocument, default=dict)
    draft_version: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20))
    result_version: Mapped[int | None] = mapped_column(Integer)


class ConflictRow(SourcesBase):
    __tablename__ = "src_conflicts"
    __table_args__ = (Index("ix_src_conflicts_source", "source_id", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40))
    change_id: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(String(500))
    component_id: Mapped[str] = mapped_column(String(200))
    field_path: Mapped[str] = mapped_column(String(500))
    base_value: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    repo_side: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    studio_side: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    status: Mapped[str] = mapped_column(String(20))
    resolution: Mapped[str | None] = mapped_column(String(20))
    resolved_value: Mapped[dict[str, Any] | None] = mapped_column(JsonDocument)
    resolved_by: Mapped[str | None] = mapped_column(String(40))
    resolved_by_name: Mapped[str | None] = mapped_column(String(200))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PullRequestRow(TimestampMixin, SourcesBase):
    __tablename__ = "src_pull_requests"
    __table_args__ = (Index("ix_src_pull_requests_source", "source_id", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40))
    number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(500))
    branch: Mapped[str] = mapped_column(String(200))
    base_branch: Mapped[str] = mapped_column(String(200))
    head_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    merge_sha: Mapped[str | None] = mapped_column(String(64))
    components: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument, default=list)
    review_requirement: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str | None] = mapped_column(String(300))
    opened_by: Mapped[str | None] = mapped_column(String(40))
    opened_by_name: Mapped[str | None] = mapped_column(String(200))
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDeliveryRow(SourcesBase):
    __tablename__ = "src_webhook_deliveries"
    __table_args__ = (UniqueConstraint("source_id", "delivery_id", name="uq_src_webhook_deliveries_delivery"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))
    delivery_id: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(60))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
