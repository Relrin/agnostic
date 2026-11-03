"""notifications: org channels, defaults, personal preferences and quiet hours, the inbox, deliveries.

Revision ID: t0001_notifications
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t0001_notifications"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("notifications",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _at(name: str, *, nullable: bool = False) -> sa.Column[Any]:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True))
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp())


def upgrade() -> None:
    op.create_table(
        "ntf_channels",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("config_enc", sa.Text(), nullable=False),
        sa.Column("events", JSON, nullable=False),
        sa.Column("instance_ids", JSON, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(40)),
        _at("created_at"),
        _at("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_ntf_channels"),
        schema="agnostic",
    )
    op.create_table(
        "ntf_defaults",
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("channels", JSON, nullable=False),
        _at("updated_at"),
        sa.PrimaryKeyConstraint("event_type", name="pk_ntf_defaults"),
        schema="agnostic",
    )
    op.create_table(
        "ntf_preferences",
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("channels", JSON, nullable=False),
        _at("updated_at"),
        sa.PrimaryKeyConstraint("user_id", "event_type", name="pk_ntf_preferences"),
        schema="agnostic",
    )
    op.create_table(
        "ntf_quiet_hours",
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("start_time", sa.String(5), nullable=False),
        sa.Column("end_time", sa.String(5), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_ntf_quiet_hours"),
        schema="agnostic",
    )
    op.create_table(
        "ntf_inbox",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("link", sa.String(1000)),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("payload", JSON, nullable=False),
        _at("created_at"),
        _at("read_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ntf_inbox"),
        schema="agnostic",
    )
    op.create_index("ix_ntf_inbox_user_id", "ntf_inbox", ["user_id", "created_at"], schema="agnostic")
    op.create_table(
        "ntf_deliveries",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("channel_id", sa.String(40)),
        sa.Column("user_id", sa.String(40)),
        sa.Column("target", sa.String(500), nullable=False),
        sa.Column("message", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("message_ref", sa.String(100)),
        _at("created_at"),
        _at("sent_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ntf_deliveries"),
        schema="agnostic",
    )
    op.create_index("ix_ntf_deliveries_channel_id", "ntf_deliveries", ["channel_id", "created_at"], schema="agnostic")


def downgrade() -> None:
    op.drop_index("ix_ntf_deliveries_channel_id", table_name="ntf_deliveries", schema="agnostic")
    op.drop_table("ntf_deliveries", schema="agnostic")
    op.drop_index("ix_ntf_inbox_user_id", table_name="ntf_inbox", schema="agnostic")
    op.drop_table("ntf_inbox", schema="agnostic")
    op.drop_table("ntf_quiet_hours", schema="agnostic")
    op.drop_table("ntf_preferences", schema="agnostic")
    op.drop_table("ntf_defaults", schema="agnostic")
    op.drop_table("ntf_channels", schema="agnostic")
