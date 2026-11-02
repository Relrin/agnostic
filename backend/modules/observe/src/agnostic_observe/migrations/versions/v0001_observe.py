"""observe: price tables and the trace-comparison cache.

Revision ID: v0001_observe
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v0001_observe"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("observe",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "obs_price_tables",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("input_per_1m", sa.Float(), nullable=False),
        sa.Column("output_per_1m", sa.Float(), nullable=False),
        sa.Column("cache_read_per_1m", sa.Float()),
        sa.Column("reasoning_per_1m", sa.Float()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("updated_by", sa.String(40)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_obs_price_tables"),
        schema="agnostic",
    )
    op.create_index("ix_obs_price_tables_instance_id", "obs_price_tables", ["instance_id"], schema="agnostic")
    op.create_table(
        "obs_trace_comparisons",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("trace_id", sa.String(200), nullable=False),
        sa.Column("baseline_trace_id", sa.String(200), nullable=False),
        sa.Column("result", JSON, nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.PrimaryKeyConstraint("instance_id", "trace_id", "baseline_trace_id", name="pk_obs_trace_comparisons"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("obs_trace_comparisons", schema="agnostic")
    op.drop_table("obs_price_tables", schema="agnostic")
