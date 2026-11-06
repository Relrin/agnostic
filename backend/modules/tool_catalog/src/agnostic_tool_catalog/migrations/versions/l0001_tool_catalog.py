"""tool_catalog: approved MCP servers and Agno toolkits, where they apply, and what each bridge last pulled.

Revision ID: l0001_tool_catalog
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l0001_tool_catalog"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("tool_catalog",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "tcat_entries",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("registry_name", sa.String(63), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("owner_group_id", sa.String(40)),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(60)),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("transport", sa.String(20)),
        sa.Column("toolkit_key", sa.String(80)),
        sa.Column("config", JSON, nullable=False),
        sa.Column("requires_confirmation_tools", JSON, nullable=False),
        sa.Column("local", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_tcat_entries"),
        sa.UniqueConstraint("registry_name", name="uq_tcat_entries_registry_name"),
        schema="agnostic",
    )
    op.create_index("ix_tcat_entries_level", "tcat_entries", ["level", "owner_group_id"], schema="agnostic")
    op.create_table(
        "tcat_entry_instances",
        sa.Column("entry_id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("entry_id", "instance_id", name="pk_tcat_entry_instances"),
        schema="agnostic",
    )
    op.create_table(
        "tcat_sync_state",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("manifest_etag", sa.String(80)),
        sa.Column("entries", sa.Integer(), nullable=False),
        sa.Column("bridge_version", sa.String(40)),
        sa.Column("last_pull_ip", sa.String(64)),
        sa.Column("last_pulled_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("instance_id", name="pk_tcat_sync_state"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("tcat_sync_state", schema="agnostic")
    op.drop_table("tcat_entry_instances", schema="agnostic")
    op.drop_index("ix_tcat_entries_level", table_name="tcat_entries", schema="agnostic")
    op.drop_table("tcat_entries", schema="agnostic")
