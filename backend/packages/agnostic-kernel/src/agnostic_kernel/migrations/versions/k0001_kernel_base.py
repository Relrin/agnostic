"""Kernel base: schema extensions, Procrastinate job tables, job progress.

Revision ID: k0001_kernel_base
Revises:
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import is_postgresql

revision: str = "k0001_kernel_base"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("kernel",)
depends_on: str | Sequence[str] | None = None

# PostgreSQL only: SQLite installs use the in-memory job queue and have no extensions.
# Frozen copy of procrastinate 3.10.0 `sql/schema.sql`. Upgrading Procrastinate means a new kernel revision that
# applies its migration scripts; this file never changes.
PROCRASTINATE_SCHEMA = Path(__file__).with_name("k0001_procrastinate_3_10_0.sql")


def _run_script(sql: str) -> None:
    """Run a multi-statement script through the raw asyncpg connection (simple query protocol)."""
    raw = op.get_bind().connection.dbapi_connection
    assert raw is not None

    async def execute(driver_connection: Any) -> None:  # noqa: ANN401  (asyncpg connection)
        await driver_connection.execute(sql)

    raw.run_async(execute)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def upgrade() -> None:
    if is_postgresql(op.get_bind()):
        op.execute("CREATE EXTENSION IF NOT EXISTS citext")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        op.execute("CREATE SCHEMA IF NOT EXISTS procrastinate")
        op.execute("SET LOCAL search_path TO procrastinate")
        _run_script(PROCRASTINATE_SCHEMA.read_text(encoding="utf-8"))
        op.execute("SET LOCAL search_path TO agnostic, public")

    op.create_table(
        "kernel_job_progress",
        sa.Column("job_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=200), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_kernel_job_progress")),
        schema="agnostic",
    )


def downgrade() -> None:
    op.drop_table("kernel_job_progress", schema="agnostic")
    if is_postgresql(op.get_bind()):
        op.execute("DROP SCHEMA IF EXISTS procrastinate CASCADE")
