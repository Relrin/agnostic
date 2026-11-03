"""sources: connections, sources and what moves between repositories and Studio.

Path mappings, sync policies, file bindings, changes, conflicts, pull requests and webhook deliveries.

Revision ID: x0001_sources
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x0001_sources"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("sources",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "src_changes",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("component_kind", sa.String(20)),
        sa.Column("component_id", sa.String(200)),
        sa.Column("binding_id", sa.String(40)),
        sa.Column("base_sha", sa.String(64)),
        sa.Column("commit_sha", sa.String(64)),
        sa.Column("blob", sa.String(64)),
        sa.Column("author_name", sa.String(200)),
        sa.Column("author_email", sa.String(320)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("message", sa.Text()),
        sa.Column("additions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("before_code", sa.Text()),
        sa.Column("after_code", sa.Text()),
        sa.Column("config", JSON),
        sa.Column("base_config", JSON),
        sa.Column("outcome", JSON, nullable=False),
        sa.Column("diagnostics", JSON, nullable=False),
        sa.Column("incoming_marks", JSON, nullable=False),
        sa.Column("draft_version", sa.Integer()),
        sa.Column("summary", sa.Text()),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_version", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_changes"),
        schema="agnostic",
    )
    op.create_index("ix_src_changes_source", "src_changes", ["source_id", "direction", "status"], schema="agnostic")
    op.create_table(
        "src_conflicts",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("change_id", sa.String(40), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("field_path", sa.String(500), nullable=False),
        sa.Column("base_value", JSON, nullable=False),
        sa.Column("repo_side", JSON, nullable=False),
        sa.Column("studio_side", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolution", sa.String(20)),
        sa.Column("resolved_value", JSON),
        sa.Column("resolved_by", sa.String(40)),
        sa.Column("resolved_by_name", sa.String(200)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_conflicts"),
        schema="agnostic",
    )
    op.create_index("ix_src_conflicts_source", "src_conflicts", ["source_id", "status"], schema="agnostic")
    op.create_table(
        "src_connections",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("auth_kind", sa.String(20), nullable=False),
        sa.Column("access", sa.String(20), nullable=False),
        sa.Column("api_url", sa.String(500)),
        sa.Column("web_url", sa.String(500)),
        sa.Column("app_slug", sa.String(200)),
        sa.Column("installation_id", sa.String(40)),
        sa.Column("account", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("config_enc", sa.Text()),
        sa.Column("created_by", sa.String(40)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_connections"),
        schema="agnostic",
    )
    op.create_table(
        "src_file_bindings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("component_kind", sa.String(20), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("last_synced_sha", sa.String(64)),
        sa.Column("last_synced_version", sa.Integer()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("synced_code", sa.Text()),
        sa.Column("synced_config", JSON),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_file_bindings"),
        sa.UniqueConstraint("source_id", "path", "component_id", name="uq_src_file_bindings_file"),
        schema="agnostic",
    )
    op.create_index("ix_src_file_bindings_component", "src_file_bindings", ["component_id"], schema="agnostic")
    op.create_table(
        "src_path_mappings",
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("glob", sa.String(500), nullable=False),
        sa.Column("target_kind", sa.String(20), nullable=False),
        sa.Column("writable", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("source_id", "position", name="pk_src_path_mappings"),
        schema="agnostic",
    )
    op.create_table(
        "src_pull_requests",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("branch", sa.String(200), nullable=False),
        sa.Column("base_branch", sa.String(200), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("merge_sha", sa.String(64)),
        sa.Column("components", JSON, nullable=False),
        sa.Column("review_requirement", sa.String(300)),
        sa.Column("title", sa.String(300)),
        sa.Column("opened_by", sa.String(40)),
        sa.Column("opened_by_name", sa.String(200)),
        sa.Column("merged_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_pull_requests"),
        schema="agnostic",
    )
    op.create_index("ix_src_pull_requests_source", "src_pull_requests", ["source_id", "status"], schema="agnostic")
    op.create_table(
        "src_sources",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("connection_id", sa.String(40)),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("repo", sa.String(300), nullable=False),
        sa.Column("branch", sa.String(200), nullable=False),
        sa.Column("clone_url", sa.String(500)),
        sa.Column("local_path", sa.String(500)),
        sa.Column("convention", JSON),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_detail", sa.Text()),
        sa.Column("last_fetched_sha", sa.String(64)),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("scan_report", JSON),
        sa.Column("webhook_id", sa.String(100)),
        sa.Column("webhook_secret_enc", sa.Text()),
        sa.Column("created_by", sa.String(40)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_src_sources"),
        schema="agnostic",
    )
    op.create_index("ix_src_sources_instance", "src_sources", ["instance_id"], schema="agnostic")
    op.create_table(
        "src_sync_policies",
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("pull_mode", sa.String(30), nullable=False),
        sa.Column("publish_mode", sa.String(30), nullable=False),
        sa.Column("branch_template", sa.String(200), nullable=False),
        sa.Column("commit_template", sa.String(300), nullable=False),
        sa.Column("block_publish_until_merged", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("source_id", name="pk_src_sync_policies"),
        schema="agnostic",
    )
    op.create_table(
        "src_webhook_deliveries",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("delivery_id", sa.String(200), nullable=False),
        sa.Column("event", sa.String(60), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id", name="pk_src_webhook_deliveries"),
        sa.UniqueConstraint("source_id", "delivery_id", name="uq_src_webhook_deliveries_delivery"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("src_webhook_deliveries", schema="agnostic")
    op.drop_table("src_sync_policies", schema="agnostic")
    op.drop_index("ix_src_sources_instance", table_name="src_sources", schema="agnostic")
    op.drop_table("src_sources", schema="agnostic")
    op.drop_index("ix_src_pull_requests_source", table_name="src_pull_requests", schema="agnostic")
    op.drop_table("src_pull_requests", schema="agnostic")
    op.drop_table("src_path_mappings", schema="agnostic")
    op.drop_index("ix_src_file_bindings_component", table_name="src_file_bindings", schema="agnostic")
    op.drop_table("src_file_bindings", schema="agnostic")
    op.drop_table("src_connections", schema="agnostic")
    op.drop_index("ix_src_conflicts_source", table_name="src_conflicts", schema="agnostic")
    op.drop_table("src_conflicts", schema="agnostic")
    op.drop_index("ix_src_changes_source", table_name="src_changes", schema="agnostic")
    op.drop_table("src_changes", schema="agnostic")
