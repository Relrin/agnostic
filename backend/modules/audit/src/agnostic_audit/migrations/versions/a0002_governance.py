"""audit: denial reasons, saved views, exports, retention and archive policy, archives, SIEM sinks, ingestion cursors.

Revision ID: a0002_governance
Revises: a0001_audit_events
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "a0002_governance"
down_revision: str | Sequence[str] | None = "a0001_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()
SOURCE_INDEX = "ix_audit_events_source_source_event_id"


def _schema() -> str | None:
    # Alembic renders ALTER TABLE itself, outside the engine's schema_translate_map: no schema on SQLite.
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    # On PostgreSQL the column and the index are added to the partitioned parent and propagate to every partition.
    op.add_column("audit_events", sa.Column("denial_reason", sa.Text()), schema=_schema())
    if is_postgresql(op.get_bind()):
        # A unique index on a partitioned table must include the partition key, which would make it useless for
        # de-duplication; ingestion de-duplicates by looking ingested ids up instead.
        op.create_index(SOURCE_INDEX, "audit_events", ["source", "source_event_id"], schema="agnostic")
    else:
        op.create_index(
            SOURCE_INDEX,
            "audit_events",
            ["source", "source_event_id"],
            unique=True,
            schema="agnostic",
            sqlite_where=sa.text("source_event_id IS NOT NULL"),
        )

    op.create_table(
        "audit_saved_views",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(200)),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("filters", JSON, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_saved_views")),
        schema="agnostic",
    )
    op.create_index("ix_audit_saved_views_owner_id", "audit_saved_views", ["owner_id"], schema="agnostic")

    op.create_table(
        "audit_exports",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("filters", JSON, nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("row_count", sa.Integer()),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("content", sa.LargeBinary()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_exports")),
        sa.CheckConstraint("format IN ('csv', 'jsonl')", name=op.f("ck_audit_exports_format")),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_audit_exports_status")),
        schema="agnostic",
    )
    op.create_index(
        "ix_audit_exports_requested_by_created_at", "audit_exports", ["requested_by", "created_at"], schema="agnostic"
    )

    op.create_table(
        "audit_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hot_retention_days", sa.Integer(), nullable=False, server_default="400"),
        sa.Column("archive_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("endpoint", sa.String(512)),
        sa.Column("bucket", sa.String(255)),
        sa.Column("prefix", sa.String(512), nullable=False, server_default=""),
        sa.Column("region", sa.String(64), nullable=False, server_default="us-east-1"),
        sa.Column("access_key_id", sa.String(255)),
        sa.Column("secret_enc", sa.Text()),
        sa.Column("object_lock_mode", sa.String(12), nullable=False, server_default="off"),
        sa.Column("archive_retention_days", sa.Integer()),
        sa.Column("hash_chain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_archive_at", sa.DateTime(timezone=True)),
        sa.Column("last_archive_error", sa.Text()),
        sa.Column("updated_by", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_policy")),
        sa.CheckConstraint("id = 1", name=op.f("ck_audit_policy_single_row")),
        sa.CheckConstraint(
            "object_lock_mode IN ('off', 'governance', 'compliance')", name=op.f("ck_audit_policy_object_lock_mode")
        ),
        schema="agnostic",
    )

    op.create_table(
        "audit_archives",
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("manifest_key", sa.String(1024), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("chain_head", sa.String(64)),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.Column("restored_at", sa.DateTime(timezone=True)),
        sa.Column("restore_expires_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("month", name=op.f("pk_audit_archives")),
        schema="agnostic",
    )

    op.create_table(
        "audit_sinks",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("config_enc", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(10), nullable=False, server_default="ok"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_sinks")),
        sa.CheckConstraint("kind IN ('https_webhook', 'syslog', 'otlp_logs')", name=op.f("ck_audit_sinks_kind")),
        sa.CheckConstraint("format IN ('json', 'ocsf', 'cef')", name=op.f("ck_audit_sinks_format")),
        sa.CheckConstraint("status IN ('ok', 'failing', 'paused')", name=op.f("ck_audit_sinks_status")),
        schema="agnostic",
    )
    op.create_table(
        "audit_sink_cursors",
        sa.Column("sink_id", sa.String(40), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("sink_id", name=op.f("pk_audit_sink_cursors")),
        sa.ForeignKeyConstraint(
            ["sink_id"],
            ["agnostic.audit_sinks.id"],
            name=op.f("fk_audit_sink_cursors_sink_id_audit_sinks"),
            ondelete="CASCADE",
        ),
        schema="agnostic",
    )
    op.create_table(
        "audit_ingest_cursors",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("stream", sa.String(20), nullable=False),
        sa.Column("cursor", sa.String(200)),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("instance_id", "stream", name=op.f("pk_audit_ingest_cursors")),
        sa.CheckConstraint("stream IN ('decisions', 'audit')", name=op.f("ck_audit_ingest_cursors_stream")),
        schema="agnostic",
    )


def downgrade() -> None:
    for table in (
        "audit_ingest_cursors",
        "audit_sink_cursors",
        "audit_sinks",
        "audit_archives",
        "audit_policy",
        "audit_exports",
        "audit_saved_views",
    ):
        op.drop_table(table, schema="agnostic")
    op.drop_index(SOURCE_INDEX, table_name="audit_events", schema="agnostic")
    op.drop_column("audit_events", "denial_reason", schema=_schema())
