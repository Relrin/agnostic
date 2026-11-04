"""audit: index events by resource, so "history of this agent / session" links don't read every partition.

On an installation that already holds millions of events, creating an index on the partitioned table locks each
partition while it builds. The upgrade guide gives the online alternative (an index ``ON ONLY`` the parent, then
``CREATE INDEX CONCURRENTLY`` per partition and ``ATTACH PARTITION``); run it before this migration and this one is a
no-op.

Revision ID: a0003_resource_index
Revises: a0002_governance
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "a0003_resource_index"
down_revision: str | Sequence[str] | None = "a0002_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_audit_events_resource_id_occurred_at"


def upgrade() -> None:
    if is_postgresql(op.get_bind()):
        op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON {SCHEMA}.audit_events (resource_id, occurred_at)")
        return
    op.create_index(INDEX, "audit_events", ["resource_id", "occurred_at"])


def downgrade() -> None:
    schema = SCHEMA if is_postgresql(op.get_bind()) else None
    op.drop_index(INDEX, table_name="audit_events", schema=schema)
