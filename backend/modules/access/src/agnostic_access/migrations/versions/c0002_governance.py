"""access: role versions and temporary access requests.

Revision ID: c0002_governance
Revises: c0001_access
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0002_governance"
down_revision: str | Sequence[str] | None = "c0001_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "access_role_versions",
        sa.Column("role_id", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSON, nullable=False),
        sa.Column("changed_by", sa.String(200), nullable=False),
        sa.Column("changed_by_name", sa.String(200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("role_id", "version", name=op.f("pk_access_role_versions")),
        schema="agnostic",
    )
    op.create_table(
        "access_temp_grant_requests",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("requester_id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("role_id", sa.String(40)),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("decided_by", sa.String(40)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.Column("binding_id", sa.String(40)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_temp_grant_requests")),
        schema="agnostic",
    )
    for column in ("status", "requester_id", "binding_id"):
        op.create_index(
            f"ix_access_temp_grant_requests_{column}", "access_temp_grant_requests", [column], schema="agnostic"
        )
    op.create_index("ix_access_bindings_expires_at", "access_bindings", ["expires_at"], schema="agnostic")


def downgrade() -> None:
    op.drop_index("ix_access_bindings_expires_at", "access_bindings", schema="agnostic")
    op.drop_table("access_temp_grant_requests", schema="agnostic")
    op.drop_table("access_role_versions", schema="agnostic")
