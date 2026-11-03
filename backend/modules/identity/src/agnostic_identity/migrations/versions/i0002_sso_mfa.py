"""identity: sign-in providers managed in the app, the org auth policy, second factors.

``identity_credentials`` drops its (user_id, kind) uniqueness so a person can register several security keys and
recovery codes; a partial unique index keeps one password and one authenticator app per person.

Revision ID: i0002_sso_mfa
Revises: i0001_identity
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from agnostic_kernel.db import SCHEMA, is_postgresql

revision: str = "i0002_sso_mfa"
down_revision: str | Sequence[str] | None = "i0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()
SINGLE_KINDS = "kind IN ('password', 'totp')"


def _schema() -> str | None:
    # Alembic renders ALTER TABLE itself, outside the engine's schema_translate_map: no schema on SQLite.
    return SCHEMA if is_postgresql(op.get_bind()) else None


def upgrade() -> None:
    op.create_table(
        "identity_login_providers",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("preset", sa.String(20), nullable=False),
        sa.Column("config", JSON, nullable=False),
        sa.Column("allowed_email_domains", JSON, nullable=False),
        sa.Column("jit_provisioning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_login_providers")),
        schema="agnostic",
    )
    op.create_table(
        "identity_auth_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enforce_sso", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("break_glass_user_id", sa.String(40)),
        sa.Column("session_idle_minutes", sa.Integer()),
        sa.Column("session_absolute_hours", sa.Integer()),
        sa.Column("mfa_policy", sa.String(20), nullable=False, server_default="optional"),
        sa.Column("updated_by", sa.String(200)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_auth_policy")),
        schema="agnostic",
    )
    with op.batch_alter_table("identity_credentials", schema=_schema()) as batch:
        batch.drop_constraint("uq_identity_credentials_user_id_kind", type_="unique")
        batch.add_column(sa.Column("data", JSON))
        batch.add_column(sa.Column("sign_count", sa.Integer()))
    op.create_index("ix_identity_credentials_user_id", "identity_credentials", ["user_id"], schema="agnostic")
    op.create_index(
        "uq_identity_credentials_user_id_single_kind",
        "identity_credentials",
        ["user_id", "kind"],
        unique=True,
        schema="agnostic",
        postgresql_where=sa.text(SINGLE_KINDS),
        sqlite_where=sa.text(SINGLE_KINDS),
    )


def downgrade() -> None:
    op.drop_index("uq_identity_credentials_user_id_single_kind", "identity_credentials", schema="agnostic")
    op.drop_index("ix_identity_credentials_user_id", "identity_credentials", schema="agnostic")
    # Second factors can't be represented before this revision (one credential per kind).
    credentials = sa.table("identity_credentials", sa.column("kind"), schema=_schema())
    op.execute(credentials.delete().where(credentials.c.kind != "password"))
    with op.batch_alter_table("identity_credentials", schema=_schema()) as batch:
        batch.drop_column("sign_count")
        batch.drop_column("data")
        batch.create_unique_constraint("uq_identity_credentials_user_id_kind", ["user_id", "kind"])
    op.drop_table("identity_auth_policy", schema="agnostic")
    op.drop_table("identity_login_providers", schema="agnostic")
