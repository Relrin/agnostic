"""org: the groups an invitation adds people to.

Revision ID: o0002_invitation_groups
Revises: o0001_org
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "o0002_invitation_groups"
down_revision: str | Sequence[str] | None = "o0001_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    with op.batch_alter_table("org_invitations", schema=_schema()) as batch:
        batch.add_column(sa.Column("group_ids", JSON, nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("org_invitations", schema=_schema()) as batch:
        batch.drop_column("group_ids")
