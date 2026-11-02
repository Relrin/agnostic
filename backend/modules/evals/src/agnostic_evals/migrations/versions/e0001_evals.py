"""evals: datasets, cases, batches and their items, publish gates.

Revision ID: e0001_evals
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e0001_evals"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("evals",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _now() -> sa.Column[Any]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()
    )


def upgrade() -> None:
    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("eval_type", sa.String(30), nullable=False),
        sa.Column("tags", JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        _now(),
        sa.PrimaryKeyConstraint("id", name="pk_eval_datasets"),
        schema="agnostic",
    )
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("dataset_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text()),
        sa.Column("criteria", sa.Text()),
        sa.Column("expected_tool_calls", JSON),
        sa.Column("metadata", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_eval_cases"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["agnostic.eval_datasets.id"],
            name="fk_eval_cases_dataset_id_eval_datasets",
            ondelete="CASCADE",
        ),
        schema="agnostic",
    )
    op.create_index("ix_eval_cases_dataset_id", "eval_cases", ["dataset_id", "position"], schema="agnostic")
    op.create_table(
        "eval_batches",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("dataset_id", sa.String(40), nullable=False),
        sa.Column("dataset_name", sa.String(200), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("component_kind", sa.String(20), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("component_version", sa.Integer()),
        sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eval_type", sa.String(30), nullable=False),
        sa.Column("judge_model_id", sa.String(200)),
        sa.Column("judge_provider", sa.String(100)),
        sa.Column("via_bridge", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("params", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("started_by", sa.String(40), nullable=False),
        sa.Column("started_by_name", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("summary", JSON),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id", name="pk_eval_batches"),
        schema="agnostic",
    )
    op.create_index("ix_eval_batches_instance_id", "eval_batches", ["instance_id", "started_at"], schema="agnostic")
    op.create_table(
        "eval_batch_items",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("batch_id", sa.String(40), nullable=False),
        sa.Column("case_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text()),
        sa.Column("case", JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("eval_run_id", sa.String(200)),
        sa.Column("score", sa.Float()),
        sa.Column("passed", sa.Boolean()),
        sa.Column("reason", sa.Text()),
        sa.Column("actual", sa.Text()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("trace_id", sa.String(200)),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id", name="pk_eval_batch_items"),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["agnostic.eval_batches.id"],
            name="fk_eval_batch_items_batch_id_eval_batches",
            ondelete="CASCADE",
        ),
        schema="agnostic",
    )
    op.create_index("ix_eval_batch_items_batch_id", "eval_batch_items", ["batch_id", "position"], schema="agnostic")
    op.create_table(
        "eval_publish_gates",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("instance_id", sa.String(40), nullable=False),
        sa.Column("component_kind", sa.String(20), nullable=False),
        sa.Column("component_id", sa.String(200), nullable=False),
        sa.Column("dataset_id", sa.String(40), nullable=False),
        sa.Column("eval_type", sa.String(30), nullable=False),
        sa.Column("min_average", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(40)),
        _now(),
        sa.PrimaryKeyConstraint("id", name="pk_eval_publish_gates"),
        sa.UniqueConstraint(
            "instance_id",
            "component_id",
            "dataset_id",
            "eval_type",
            name="uq_eval_publish_gates_target",
        ),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("eval_publish_gates", schema="agnostic")
    op.drop_table("eval_batch_items", schema="agnostic")
    op.drop_table("eval_batches", schema="agnostic")
    op.drop_table("eval_cases", schema="agnostic")
    op.drop_table("eval_datasets", schema="agnostic")
