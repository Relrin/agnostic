"""identity: users, credentials, external identities, sessions, preferences, sign-in providers, the auth policy.

A person has at most one password and one authenticator app, but any number of security keys and recovery codes:
a partial unique index covers only the single kinds.

Revision ID: i0001_identity
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i0001_identity"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("identity",)
depends_on: str | Sequence[str] | None = "k0001_kernel_base"

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
NOW = sa.func.current_timestamp()
USERS_FK = "agnostic.identity_users.id"
SINGLE_KINDS = "kind IN ('password', 'totp')"


def upgrade() -> None:
    op.create_table(
        "identity_users",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("avatar_seed", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("locale", sa.String(35)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("created_via", sa.String(20), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_users")),
        sa.UniqueConstraint("email", name=op.f("uq_identity_users_email")),
        schema="agnostic",
    )
    op.create_table(
        "identity_credentials",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("label", sa.String(120)),
        sa.Column("data", JSON),
        sa.Column("sign_count", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["user_id"], [USERS_FK], name=op.f("fk_identity_credentials_user_id_identity_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_credentials")),
        schema="agnostic",
    )
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
    op.create_table(
        "identity_external_identities",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_provider", sa.String(320)),
        sa.Column("raw_claims", JSON),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [USERS_FK],
            name=op.f("fk_identity_external_identities_user_id_identity_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_external_identities")),
        sa.UniqueConstraint("provider_id", "subject", name=op.f("uq_identity_external_identities_provider_id_subject")),
        schema="agnostic",
    )
    op.create_index(
        op.f("ix_identity_external_identities_user_id"), "identity_external_identities", ["user_id"], schema="agnostic"
    )
    op.create_table(
        "identity_sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("method", sa.String(80), nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["user_id"], [USERS_FK], name=op.f("fk_identity_sessions_user_id_identity_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_sessions")),
        schema="agnostic",
    )
    op.create_index(
        "ix_identity_sessions_user_id_revoked_at", "identity_sessions", ["user_id", "revoked_at"], schema="agnostic"
    )
    op.create_table(
        "identity_preferences",
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", JSON),
        sa.ForeignKeyConstraint(
            ["user_id"], [USERS_FK], name=op.f("fk_identity_preferences_user_id_identity_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_identity_preferences")),
        schema="agnostic",
    )

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


def downgrade() -> None:
    for table in (
        "identity_auth_policy",
        "identity_login_providers",
        "identity_preferences",
        "identity_sessions",
        "identity_external_identities",
        "identity_credentials",
        "identity_users",
    ):
        op.drop_table(table, schema="agnostic")
