"""approvals: routes that name groups.

Revision ID: p0002_group_routes
Revises: p0001_approvals
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "p0002_group_routes"
down_revision: str | Sequence[str] | None = "p0001_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    with op.batch_alter_table("apr_routes", schema=_schema()) as batch:
        batch.add_column(sa.Column("group_ids", JSON, nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("apr_routes", schema=_schema()) as batch:
        batch.drop_column("group_ids")
