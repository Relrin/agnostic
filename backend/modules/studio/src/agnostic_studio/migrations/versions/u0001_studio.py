"""studio: component and version metadata, registry used-by index, promotions.

Revision ID: u0001_studio
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "u0001_studio"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("studio",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "studio_component_meta",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("owner_group_id", sa.String(40)),
        sa.Column("labels", JSON, nullable=False),
        sa.Column("last_known_current_version", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("instance_id", "component_id", name="pk_studio_component_meta"),
        schema="agnostic",
    )
    op.create_table(
        "studio_version_meta",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.String(40)),
        sa.Column("author_name", sa.String(200)),
        sa.Column("updated_by", sa.String(40)),
        sa.Column("updated_by_name", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("change_summary", sa.Text()),
        sa.Column("based_on_version", sa.Integer()),
        sa.Column("eval_status", sa.String(20)),
        sa.Column("published_by", sa.String(40)),
        sa.Column("published_by_name", sa.String(200)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("promoted_from", JSON),
        sa.PrimaryKeyConstraint("instance_id", "component_id", "version", name="pk_studio_version_meta"),
        schema="agnostic",
    )
    op.create_table(
        "studio_registry_index",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("entry_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("used_by", JSON, nullable=False),
        sa.Column("studio_available", sa.Boolean()),
        sa.Column("reason", sa.Text()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("instance_id", "entry_type", "name", name="pk_studio_registry_index"),
        schema="agnostic",
    )
    op.create_table(
        "studio_promotions",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("from_instance", sa.String(40), nullable=False),
        sa.Column("to_instance", sa.String(40), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("component_kind", sa.String(20), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer()),
        sa.Column("include_children", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("report", JSON, nullable=False),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_by_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name="pk_studio_promotions"),
        schema="agnostic",
    )
    op.create_index(
        "ix_studio_promotions_component",
        "studio_promotions",
        ["from_instance", "component_id", "created_at"],
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_index("ix_studio_promotions_component", table_name="studio_promotions", schema="agnostic")
    op.drop_table("studio_promotions", schema="agnostic")
    op.drop_table("studio_registry_index", schema="agnostic")
    op.drop_table("studio_version_meta", schema="agnostic")
    op.drop_table("studio_component_meta", schema="agnostic")
