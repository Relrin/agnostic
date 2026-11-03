"""service_accounts: accounts, their native tokens per instance, and gateway tokens.

Revision ID: w0001_service_accounts
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w0001_service_accounts"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("service_accounts",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "sa_accounts",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("principal", sa.String(70), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("scope_source", sa.String(10), nullable=False),
        sa.Column("role_id", sa.String(40)),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("instance_ids", JSON, nullable=False),
        sa.Column("forwards_user_id", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_by_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sa_accounts")),
        schema="agnostic",
    )
    op.create_index(
        "uq_sa_accounts_name_live",
        "sa_accounts",
        ["name"],
        unique=True,
        schema="agnostic",
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "sa_instance_tokens",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("sa_id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("agentos_sa_id", sa.String(200), nullable=False),
        sa.Column("token_prefix", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("scopes", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sa_instance_tokens")),
        schema="agnostic",
    )
    op.create_index("ix_sa_instance_tokens_sa_id", "sa_instance_tokens", ["sa_id"], schema="agnostic")
    op.create_index(
        "ix_sa_instance_tokens_instance_id_status", "sa_instance_tokens", ["instance_id", "status"], schema="agnostic"
    )
    op.create_table(
        "sa_gateway_tokens",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("sa_id", sa.String(40), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("grace_until", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(200)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_ip", sa.String(64)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sa_gateway_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sa_gateway_tokens_token_hash")),
        schema="agnostic",
    )
    op.create_index("ix_sa_gateway_tokens_sa_id", "sa_gateway_tokens", ["sa_id"], schema="agnostic")


def downgrade() -> None:
    op.drop_table("sa_gateway_tokens", schema="agnostic")
    op.drop_table("sa_instance_tokens", schema="agnostic")
    op.drop_table("sa_accounts", schema="agnostic")
