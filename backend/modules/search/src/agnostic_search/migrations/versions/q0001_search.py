"""search: the command-palette index.

Revision ID: q0001_search
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agnostic_kernel.db import is_postgresql

revision: str = "q0001_search"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("search",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("id", sa.String(400), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("ref", sa.String(200), nullable=False),
        sa.Column("instance_id", sa.String(40)),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("url_path", sa.String(500), nullable=False, server_default=""),
        sa.Column("required_scope", sa.String(120)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.PrimaryKeyConstraint("id", name="pk_search_documents"),
        schema="agnostic",
    )
    op.create_index("ix_search_documents_provider", "search_documents", ["provider"], schema="agnostic")
    op.create_index("ix_search_documents_ref", "search_documents", ["ref"], schema="agnostic")
    bind = op.get_bind()
    if not is_postgresql(bind):
        return
    op.execute(
        "ALTER TABLE agnostic.search_documents ADD COLUMN tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(ref, '') || ' ' || coalesce(body, ''))) STORED"
    )
    op.execute("CREATE INDEX ix_search_documents_tsv ON agnostic.search_documents USING gin (tsv)")
    # Trigram similarity only when the extension is already there (creating it may need a superuser).
    if bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).first() is not None:
        op.execute(
            "CREATE INDEX ix_search_documents_title_trgm ON agnostic.search_documents "
            "USING gin (lower(title) gin_trgm_ops)"
        )


def downgrade() -> None:
    op.drop_table("search_documents", schema="agnostic")
