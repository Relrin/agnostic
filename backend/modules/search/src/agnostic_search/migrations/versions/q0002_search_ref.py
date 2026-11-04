"""search: index the exact-reference match.

The palette query ORs full-text, title LIKE and ``ref = :exact``. Without an index on ``ref`` PostgreSQL can't
combine the three as a bitmap OR and reads the whole table on every keystroke.

Revision ID: q0002_search_ref
Revises: q0001_search
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "q0002_search_ref"
down_revision: str | Sequence[str] | None = "q0001_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_search_documents_ref", "search_documents", ["ref"], schema="agnostic")


def downgrade() -> None:
    op.drop_index("ix_search_documents_ref", table_name="search_documents", schema="agnostic")
