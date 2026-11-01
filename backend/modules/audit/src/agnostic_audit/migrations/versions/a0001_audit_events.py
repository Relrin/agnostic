"""audit: append-only events, partitioned by month on PostgreSQL.

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


def downgrade() -> None:
    op.drop_table("audit_events", schema="agnostic")
    if is_postgresql(op.get_bind()):
        op.execute("DROP FUNCTION IF EXISTS agnostic.audit_events_append_only()")
