"""access: scope catalog, access roles, bindings.

Revision ID: c0001_access
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c0001_access"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("access",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "access_scope_catalog",
        sa.Column("scope", sa.String(120), nullable=False),
        sa.Column("family", sa.String(60), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("resource_kind", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("agentos_min_version", sa.String(20)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("privileged", sa.Boolean(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("scope", name=op.f("pk_access_scope_catalog")),
        schema="agnostic",
    )
    op.create_table(
        "access_roles",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("color", sa.String(20), nullable=False),
        sa.Column("permissions", JSON, nullable=False),
        sa.Column("run_scope", JSON, nullable=False),
        sa.Column("bindable_instance_ids", JSON),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_roles")),
        sa.UniqueConstraint("slug", name=op.f("uq_access_roles_slug")),
        schema="agnostic",
    )
    op.create_table(
        "access_bindings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("principal_kind", sa.String(20), nullable=False),
        sa.Column("principal_id", sa.String(200), nullable=False),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("role_id", sa.String(40)),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_bindings")),
        schema="agnostic",
    )
    op.create_index(
        "ix_access_bindings_principal_kind_principal_id",
        "access_bindings",
        ["principal_kind", "principal_id"],
        schema="agnostic",
    )
    op.create_index("ix_access_bindings_instance_id", "access_bindings", ["instance_id"], schema="agnostic")


def downgrade() -> None:
    op.drop_table("access_bindings", schema="agnostic")
    op.drop_table("access_roles", schema="agnostic")
    op.drop_table("access_scope_catalog", schema="agnostic")
