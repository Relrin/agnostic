"""approvals: routing rules, views, control-plane events and per-instance expiry policy.

Revision ID: p0001_approvals
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "p0001_approvals"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("approvals",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _at(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp())


def upgrade() -> None:
    op.create_table(
        "apr_routes",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tool_name", sa.String(200)),
        sa.Column("component_kind", sa.String(20)),
        sa.Column("component_ids", JSON, nullable=False),
        sa.Column("member_ids", JSON, nullable=False),
        sa.Column("role_ids", JSON, nullable=False),
        sa.Column("group_ids", JSON, nullable=False),
        sa.Column("channels", JSON, nullable=False),
        sa.Column("channel_ids", JSON, nullable=False),
        sa.Column("created_by", sa.String(40)),
        _at("created_at"),
        _at("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_apr_routes"),
        schema="agnostic",
    )
    op.create_index("ix_apr_routes_instance_id", "apr_routes", ["instance_id"], schema="agnostic")
    op.create_table(
        "apr_views",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("approval_id", sa.String(200), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        _at("viewed_at"),
        sa.PrimaryKeyConstraint("instance_id", "approval_id", "user_id", name="pk_apr_views"),
        schema="agnostic",
    )
    op.create_table(
        "apr_events",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("approval_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("detail", JSON, nullable=False),
        sa.Column("actor", sa.String(40)),
        _at("at"),
        sa.PrimaryKeyConstraint("id", name="pk_apr_events"),
        schema="agnostic",
    )
    op.create_index("ix_apr_events_approval", "apr_events", ["instance_id", "approval_id"], schema="agnostic")
    op.create_table(
        "apr_policies",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("enforce_expiry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ttl_hours", sa.Integer()),
        sa.Column("updated_by", sa.String(40)),
        _at("updated_at"),
        sa.PrimaryKeyConstraint("instance_id", name="pk_apr_policies"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("apr_policies", schema="agnostic")
    op.drop_index("ix_apr_events_approval", table_name="apr_events", schema="agnostic")
    op.drop_table("apr_events", schema="agnostic")
    op.drop_table("apr_views", schema="agnostic")
    op.drop_index("ix_apr_routes_instance_id", table_name="apr_routes", schema="agnostic")
    op.drop_table("apr_routes", schema="agnostic")
