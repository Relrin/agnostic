"""directory: groups and their members, SCIM tokens and users, mapping rules, Google Workspace sync, settings.

Revision ID: r0001_directory
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "r0001_directory"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("directory",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

NOW = sa.func.current_timestamp()
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "dir_groups",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(200)),
        sa.Column("external_name", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_groups")),
        sa.UniqueConstraint("name_key", name=op.f("uq_dir_groups_name_key")),
        schema="agnostic",
    )
    op.create_index("ix_dir_groups_source_external_id", "dir_groups", ["source", "external_id"], schema="agnostic")
    op.create_table(
        "dir_group_members",
        sa.Column("group_id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("role", sa.String(10), nullable=False, server_default="member"),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("rule_id", sa.String(40)),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["agnostic.dir_groups.id"],
            name=op.f("fk_dir_group_members_group_id_dir_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_dir_group_members")),
        schema="agnostic",
    )
    op.create_index("ix_dir_group_members_user_id", "dir_group_members", ["user_id"], schema="agnostic")
    op.create_table(
        "dir_scim_tokens",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_from", sa.String(40)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_scim_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_dir_scim_tokens_token_hash")),
        schema="agnostic",
    )
    op.create_table(
        "dir_scim_sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_request_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("counts", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_scim_sync_state")),
        schema="agnostic",
    )
    op.create_table(
        "dir_scim_users",
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(200)),
        sa.Column("user_name", sa.String(320), nullable=False),
        sa.Column("user_name_key", sa.String(320), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("raw", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_dir_scim_users")),
        sa.UniqueConstraint("user_name_key", name=op.f("uq_dir_scim_users_user_name_key")),
        schema="agnostic",
    )
    op.create_index("ix_dir_scim_users_external_id", "dir_scim_users", ["external_id"], schema="agnostic")
    op.create_table(
        "dir_mapping_rules",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("provider_id", sa.String(64)),
        sa.Column("idp_group", sa.String(200), nullable=False),
        sa.Column("group_id", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["agnostic.dir_groups.id"],
            name=op.f("fk_dir_mapping_rules_group_id_dir_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_mapping_rules")),
        schema="agnostic",
    )
    op.create_table(
        "dir_google_sync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("config_enc", sa.Text()),
        sa.Column("group_filter", JSON, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("counts", JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_google_sync")),
        schema="agnostic",
    )
    op.create_table(
        "dir_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deprovision", sa.String(10), nullable=False, server_default="disable"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dir_settings")),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("dir_settings", schema="agnostic")
    op.drop_table("dir_google_sync", schema="agnostic")
    op.drop_table("dir_mapping_rules", schema="agnostic")
    op.drop_table("dir_scim_users", schema="agnostic")
    op.drop_table("dir_scim_sync_state", schema="agnostic")
    op.drop_table("dir_scim_tokens", schema="agnostic")
    op.drop_table("dir_group_members", schema="agnostic")
    op.drop_table("dir_groups", schema="agnostic")
