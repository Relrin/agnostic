"""artifacts: share links to artefacts, each pinned to one stored object and its hash.

Revision ID: h0001_artifacts
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h0001_artifacts"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("artifacts",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"


def upgrade() -> None:
    op.create_table(
        "art_shares",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("audience", sa.String(10), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_by_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_opened_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_art_shares"),
        sa.UniqueConstraint("token_hash", name="uq_art_shares_token_hash"),
        schema="agnostic",
    )
    op.create_index("ix_art_shares_instance_session", "art_shares", ["instance_id", "session_id"], schema="agnostic")


def downgrade() -> None:
    op.drop_index("ix_art_shares_instance_session", table_name="art_shares", schema="agnostic")
    op.drop_table("art_shares", schema="agnostic")
