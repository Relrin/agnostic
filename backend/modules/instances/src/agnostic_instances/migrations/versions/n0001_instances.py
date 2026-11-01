"""instances: registry, snapshots, capability matrix, JWT key pairs.

Revision ID: n0001_instances
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "n0001_instances"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("instances",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()
INSTANCE_FK = "agnostic.inst_instances.id"


def upgrade() -> None:
    op.create_table(
        "inst_instances",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("env_tag", sa.String(20), nullable=False),
        sa.Column("endpoint_url", sa.String(2048), nullable=False),
        sa.Column("network_mode", sa.String(20), nullable=False),
        sa.Column("os_id", sa.String(200)),
        sa.Column("agno_version", sa.String(40)),
        sa.Column("os_version", sa.String(40)),
        sa.Column("auth_mode", sa.String(20), nullable=False),
        sa.Column("user_isolation", sa.Boolean()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("sub_claim_mode", sa.String(20), nullable=False),
        sa.Column("tls_verify", sa.Boolean(), nullable=False),
        sa.Column("ca_bundle_pem", sa.Text()),
        sa.Column("security_key_enc", sa.Text()),
        sa.Column("previous_agno_version", sa.String(40)),
        sa.Column("version_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inst_instances")),
        sa.UniqueConstraint("slug", name=op.f("uq_inst_instances_slug")),
        schema="agnostic",
    )
    op.create_table(
        "inst_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", JSON),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            [INSTANCE_FK],
            name=op.f("fk_inst_snapshots_instance_id_inst_instances"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inst_snapshots")),
        schema="agnostic",
    )
    op.create_index(
        "ix_inst_snapshots_instance_id_kind_fetched_at",
        "inst_snapshots",
        ["instance_id", "kind", "fetched_at"],
        schema="agnostic",
    )
    op.create_table(
        "inst_capabilities",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("capability", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("probed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            [INSTANCE_FK],
            name=op.f("fk_inst_capabilities_instance_id_inst_instances"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instance_id", "capability", name=op.f("pk_inst_capabilities")),
        schema="agnostic",
    )
    op.create_table(
        "inst_jwt_keys",
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("kid", sa.String(64), nullable=False),
        sa.Column("alg", sa.String(10), nullable=False),
        sa.Column("public_pem", sa.Text(), nullable=False),
        sa.Column("private_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["instance_id"], [INSTANCE_FK], name=op.f("fk_inst_jwt_keys_instance_id_inst_instances"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("instance_id", "kid", name=op.f("pk_inst_jwt_keys")),
        schema="agnostic",
    )


def downgrade() -> None:
    for table in ("inst_jwt_keys", "inst_capabilities", "inst_snapshots", "inst_instances"):
        op.drop_table(table, schema="agnostic")
