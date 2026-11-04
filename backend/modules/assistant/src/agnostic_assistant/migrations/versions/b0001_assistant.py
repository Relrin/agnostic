"""assistant: AI feature settings, conversations, answers, attachments and token usage.

Revision ID: b0001_assistant
Revises:
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b0001_assistant"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("assistant",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()


def upgrade() -> None:
    op.create_table(
        "asst_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("models", JSON, nullable=False),
        sa.Column("endpoint", sa.String(500)),
        sa.Column("api_version", sa.String(40)),
        sa.Column("api_key_enc", sa.Text()),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("features", JSON, nullable=False),
        sa.Column("monthly_token_budget", sa.Integer()),
        sa.Column("user_monthly_tokens", sa.Integer()),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("redact_tool_args", sa.Boolean(), nullable=False),
        sa.Column("redact_user_messages", sa.Boolean(), nullable=False),
        sa.Column("audit_question_text", sa.Boolean(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("data_notice", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(40)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_asst_settings"),
        schema="agnostic",
    )
    op.create_table(
        "asst_conversations",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_asst_conversations"),
        schema="agnostic",
    )
    op.create_index(
        "ix_asst_conversations_owner",
        "asst_conversations",
        ["user_id", "instance_id", "updated_at"],
        schema="agnostic",
    )
    op.create_table(
        "asst_messages",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("conversation_id", sa.String(40)),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("feature", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("subject", JSON, nullable=False),
        sa.Column("subject_key", sa.String(40)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("tool_calls", JSON, nullable=False),
        sa.Column("sources", JSON, nullable=False),
        sa.Column("model", sa.String(200)),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agnostic.asst_conversations.id"],
            name=op.f("fk_asst_messages_conversation_id_asst_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asst_messages"),
        schema="agnostic",
    )
    op.create_index(
        "ix_asst_messages_conversation", "asst_messages", ["conversation_id", "created_at"], schema="agnostic"
    )
    op.create_index(
        "ix_asst_messages_reuse",
        "asst_messages",
        ["user_id", "instance_id", "kind", "subject_key"],
        schema="agnostic",
    )
    op.create_index("ix_asst_messages_created", "asst_messages", ["created_at"], schema="agnostic")
    op.create_table(
        "asst_attachments",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("message_id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("data", sa.LargeBinary()),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["agnostic.asst_messages.id"],
            name=op.f("fk_asst_attachments_message_id_asst_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asst_attachments"),
        schema="agnostic",
    )
    op.create_index("ix_asst_attachments_message", "asst_attachments", ["message_id"], schema="agnostic")
    op.create_table(
        "asst_usage",
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("feature", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("month", "user_id", "feature", name="pk_asst_usage"),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("asst_usage", schema="agnostic")
    op.drop_index("ix_asst_attachments_message", table_name="asst_attachments", schema="agnostic")
    op.drop_table("asst_attachments", schema="agnostic")
    op.drop_index("ix_asst_messages_created", table_name="asst_messages", schema="agnostic")
    op.drop_index("ix_asst_messages_reuse", table_name="asst_messages", schema="agnostic")
    op.drop_index("ix_asst_messages_conversation", table_name="asst_messages", schema="agnostic")
    op.drop_table("asst_messages", schema="agnostic")
    op.drop_index("ix_asst_conversations_owner", table_name="asst_conversations", schema="agnostic")
    op.drop_table("asst_conversations", schema="agnostic")
    op.drop_table("asst_settings", schema="agnostic")
