"""instances: client certificates (mutual TLS) and the browser URL for direct mode.

Revision ID: n0003_mtls_direct_mode
Revises: n0002_elevation
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "n0003_mtls_direct_mode"
down_revision: str | Sequence[str] | None = "n0002_elevation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _schema() -> str | None:
    # Alembic renders ALTER TABLE itself, outside the engine's schema_translate_map: no schema on SQLite.
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    schema = _schema()
    op.add_column("inst_instances", sa.Column("client_cert_pem", sa.Text(), nullable=True), schema=schema)
    op.add_column("inst_instances", sa.Column("client_key_enc", sa.Text(), nullable=True), schema=schema)
    op.add_column("inst_instances", sa.Column("browser_url", sa.String(2048), nullable=True), schema=schema)


def downgrade() -> None:
    schema = _schema()
    with op.batch_alter_table("inst_instances", schema=schema) as batch:
        batch.drop_column("browser_url")
        batch.drop_column("client_key_enc")
        batch.drop_column("client_cert_pem")
