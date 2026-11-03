"""studio: workflow canvas layouts and the code of code-backed drafts.

Revision ID: u0002_canvas_and_code
Revises: u0001_studio
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u0002_canvas_and_code"
down_revision: str | Sequence[str] | None = "u0001_studio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "studio_canvas_layouts",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("layout", JSON, nullable=False),
        sa.Column("updated_by", sa.String(40)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("instance_id", "component_id", "version", name="pk_studio_canvas_layouts"),
        schema="agnostic",
    )
    op.create_table(
        "studio_code_documents",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(40)),
        sa.Column("updated_by_name", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("instance_id", "component_id", "version", name="pk_studio_code_documents"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("studio_code_documents", schema="agnostic")
    op.drop_table("studio_canvas_layouts", schema="agnostic")
