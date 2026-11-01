"""settings: org settings and feature flags.

Revision ID: s0001_settings
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s0001_settings"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("settings",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "settings_org",
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", JSON, nullable=True),
        sa.Column("updated_by", sa.String(200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings_org")),
        schema="agnostic",
    )
    op.create_table(
        "settings_flags",
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("value", JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings_flags")),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("settings_flags", schema="agnostic")
    op.drop_table("settings_org", schema="agnostic")
