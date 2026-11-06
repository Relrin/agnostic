"""sources: remember when a source was activated.

A source activated with nothing bound (or that lost every binding since) still syncs; until now the only sign of
activation was having bindings. Sources that are active, or have bindings, count as activated when they were last
updated.

Revision ID: x0002_source_activation
Revises: x0001_sources
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "x0002_source_activation"
down_revision: str | Sequence[str] | None = "x0001_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str | None:
    # SQLite has no schemas: its tables live in the main database.
    return "agnostic" if op.get_bind().dialect.name == "postgresql" else None


def upgrade() -> None:
    schema = _schema()
    op.add_column("src_sources", sa.Column("activated_at", sa.DateTime(timezone=True)), schema=schema)
    sources = sa.table(
        "src_sources",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("activated_at", sa.DateTime(timezone=True)),
        schema=schema,
    )
    bindings = sa.table("src_file_bindings", sa.column("source_id", sa.String()), schema=schema)
    bound = sa.select(bindings.c.source_id).where(bindings.c.source_id == sources.c.id).exists()
    op.execute(
        sources.update()
        .where(sources.c.activated_at.is_(None), sa.or_(sources.c.status == "active", bound))
        .values(activated_at=sources.c.updated_at)
    )


def downgrade() -> None:
    op.drop_column("src_sources", "activated_at", schema=_schema())
