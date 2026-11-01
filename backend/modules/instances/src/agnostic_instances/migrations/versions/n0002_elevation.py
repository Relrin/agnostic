"""instances: per-instance switch for delegated elevation (ADR 0014).

Revision ID: n0002_elevation
Revises: n0001_instances
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "n0002_elevation"
down_revision: str | Sequence[str] | None = "n0001_instances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str | None:
    # Alembic renders ALTER TABLE itself, outside the engine's schema_translate_map: no schema on SQLite.
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    op.add_column(
        "inst_instances",
        sa.Column("elevation_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema=_schema(),
    )


def downgrade() -> None:
    op.drop_column("inst_instances", "elevation_enabled", schema=_schema())
