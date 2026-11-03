"""scheduler: the reasons people give when they disable a schedule.

Revision ID: d0001_scheduler
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0001_scheduler"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("scheduler",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"


def upgrade() -> None:
    op.create_table(
        "sch_notes",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("schedule_id", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("disabled_by", sa.String(40), nullable=False),
        sa.Column("disabled_by_name", sa.String(200), nullable=False),
        sa.Column(
            "disabled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.PrimaryKeyConstraint("instance_id", "schedule_id", name="pk_sch_notes"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("sch_notes", schema="agnostic")
