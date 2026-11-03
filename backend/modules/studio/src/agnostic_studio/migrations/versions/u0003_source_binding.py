"""studio: which repository file a component is synced with, and that repository's registry convention.

Revision ID: u0003_source_binding
Revises: u0002_canvas_and_code
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "u0003_source_binding"
down_revision: str | Sequence[str] | None = "u0002_canvas_and_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    with op.batch_alter_table("studio_component_meta", schema=_schema()) as batch:
        batch.add_column(sa.Column("source_binding_id", sa.String(40)))
        batch.add_column(sa.Column("code_path", sa.String(500)))
        batch.add_column(sa.Column("convention", JSON))


def downgrade() -> None:
    with op.batch_alter_table("studio_component_meta", schema=_schema()) as batch:
        batch.drop_column("convention")
        batch.drop_column("code_path")
        batch.drop_column("source_binding_id")
