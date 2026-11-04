"""org: profile (one row), members, invitations.

Revision ID: o0001_org
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "o0001_org"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("org",)
depends_on: str | Sequence[str] | None = ("k0001_kernel_base", "i0001_identity")

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "org_profile",
        sa.Column("id", sa.String(8), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("logo_url", sa.String(2048)),
        sa.Column("plan_label", sa.String(80)),
        sa.Column("seat_limit", sa.Integer()),
        sa.Column("bootstrap_token_hash", sa.String(64)),
        sa.Column("bootstrap_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_profile")),
        schema="agnostic",
    )
    op.create_table(
        "org_members",
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("org_role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("joined_via", sa.String(80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["agnostic.identity_users.id"],
            name=op.f("fk_org_members_user_id_identity_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_org_members")),
        schema="agnostic",
    )
    op.create_table(
        "org_invitations",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("org_role", sa.String(20), nullable=False),
        sa.Column("bindings", JSON, nullable=False),
        sa.Column("group_ids", JSON, nullable=False),
        sa.Column("access_ends_at", sa.DateTime(timezone=True)),
        sa.Column("invited_by", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_org_invitations_token_hash")),
        schema="agnostic",
    )
    op.create_index("ix_org_invitations_email_status", "org_invitations", ["email", "status"], schema="agnostic")


def downgrade() -> None:
    op.drop_table("org_invitations", schema="agnostic")
    op.drop_table("org_members", schema="agnostic")
    op.drop_table("org_profile", schema="agnostic")
