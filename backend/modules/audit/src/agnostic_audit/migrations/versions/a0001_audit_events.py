"""audit: append-only events, saved views, exports, retention and archive policy, archives, SIEM sinks, cursors.

Events are partitioned by month on PostgreSQL.

Revision ID: a0001_audit_events
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import is_postgresql

revision: str = "a0001_audit_events"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("audit",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()
SOURCE_INDEX = "ix_audit_events_source_source_event_id"

COLUMNS = """
    id varchar(40) NOT NULL,
    occurred_at timestamptz NOT NULL,
    request_id varchar(160),
    actor_kind varchar(20) NOT NULL,
    actor_id varchar(200) NOT NULL,
    actor_display varchar(320) NOT NULL,
    via varchar(40) NOT NULL,
    ip varchar(64),
    client varchar(512),
    action varchar(120) NOT NULL,
    resource_kind varchar(60),
    resource_id varchar(200),
    resource_display text,
    instance_id varchar(40),
    decision varchar(10) NOT NULL,
    denial_reason text,
    scope_checked varchar(200),
    missing_scopes jsonb,
    response_status integer,
    summary text NOT NULL,
    diff jsonb,
    links jsonb,
    source varchar(20) NOT NULL,
    source_event_id varchar(200),
    prev_hash varchar(64),
    hash varchar(64),
    CONSTRAINT pk_audit_events PRIMARY KEY (id, occurred_at)
"""


def _month(year: int, month: int) -> datetime:
    return datetime(year + (month - 1) // 12, (month - 1) % 12 + 1, 1, tzinfo=UTC)


def upgrade() -> None:
    if is_postgresql(op.get_bind()):
        op.execute(f"CREATE TABLE agnostic.audit_events ({COLUMNS}) PARTITION BY RANGE (occurred_at)")
        op.execute("CREATE TABLE agnostic.audit_events_default PARTITION OF agnostic.audit_events DEFAULT")
        now = datetime.now(UTC)
        for offset in range(3):
            start, end = _month(now.year, now.month + offset), _month(now.year, now.month + offset + 1)
            op.execute(
                f"CREATE TABLE agnostic.audit_events_y{start.year:04d}m{start.month:02d} "
                f"PARTITION OF agnostic.audit_events FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
            )
        # Append-only: retention drops whole partitions, nothing updates or deletes rows.
        op.execute(
            "CREATE FUNCTION agnostic.audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$"
        )
        op.execute(
            "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON agnostic.audit_events "
            "FOR EACH ROW EXECUTE FUNCTION agnostic.audit_events_append_only()"
        )
    else:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(40), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("request_id", sa.String(160)),
            sa.Column("actor_kind", sa.String(20), nullable=False),
            sa.Column("actor_id", sa.String(200), nullable=False),
            sa.Column("actor_display", sa.String(320), nullable=False),
            sa.Column("via", sa.String(40), nullable=False),
            sa.Column("ip", sa.String(64)),
            sa.Column("client", sa.String(512)),
            sa.Column("action", sa.String(120), nullable=False),
            sa.Column("resource_kind", sa.String(60)),
            sa.Column("resource_id", sa.String(200)),
            sa.Column("resource_display", sa.Text()),
            sa.Column("instance_id", sa.String(40)),
            sa.Column("decision", sa.String(10), nullable=False),
            sa.Column("denial_reason", sa.Text()),
            sa.Column("scope_checked", sa.String(200)),
            sa.Column("missing_scopes", JSON),
            sa.Column("response_status", sa.Integer()),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("diff", JSON),
            sa.Column("links", JSON),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("source_event_id", sa.String(200)),
            sa.Column("prev_hash", sa.String(64)),
            sa.Column("hash", sa.String(64)),
            sa.PrimaryKeyConstraint("id", "occurred_at", name="pk_audit_events"),
            schema="agnostic",
        )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], schema="agnostic")
    op.create_index(
        "ix_audit_events_actor_id_occurred_at", "audit_events", ["actor_id", "occurred_at"], schema="agnostic"
    )
    op.create_index("ix_audit_events_action_occurred_at", "audit_events", ["action", "occurred_at"], schema="agnostic")
    op.create_index(
        "ix_audit_events_instance_id_occurred_at", "audit_events", ["instance_id", "occurred_at"], schema="agnostic"
    )
    op.create_index(
        "ix_audit_events_resource_id_occurred_at", "audit_events", ["resource_id", "occurred_at"], schema="agnostic"
    )
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
        "audit_events",
    ):
        op.drop_table(table, schema="agnostic")
    if is_postgresql(op.get_bind()):
        op.execute("DROP FUNCTION IF EXISTS agnostic.audit_events_append_only()")
