"""gateway: route-policy overrides.

Revision ID: g0001_gateway
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g0001_gateway"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("gateway",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "gw_route_policies",
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path_pattern", sa.String(300), nullable=False),
        sa.Column("required_scopes", JSON, nullable=False),
        sa.Column("cache_ttl_s", sa.Integer(), nullable=False),
        sa.Column("audit_level", sa.String(10), nullable=False),
        sa.Column("rate_bucket", sa.String(10), nullable=False),
        sa.Column("list_filter", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("method", "path_pattern", name=op.f("pk_gw_route_policies")),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("gw_route_policies", schema="agnostic")
