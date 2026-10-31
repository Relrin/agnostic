"""hello: greetings table.

Revision ID: h0001_greetings
Revises:
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h0001_greetings"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("hello",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"


def upgrade() -> None:
    op.create_table(
        "hello_greetings",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hello_greetings")),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("hello_greetings", schema="agnostic")
