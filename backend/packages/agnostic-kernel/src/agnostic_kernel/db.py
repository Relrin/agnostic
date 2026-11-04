"""Database access: async SQLAlchemy engine for the app, libpq conninfo for Procrastinate (psycopg).

PostgreSQL is the production backend; SQLite works for development and tests. All control-plane tables are
declared in the ``agnostic`` schema and each module owns its tables (``<module>_*``) and its own ``MetaData`` built
with :func:`make_metadata`. SQLite has no schemas, so its engine maps ``agnostic`` to the main database with
``schema_translate_map``; models and migrations stay identical across backends.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg.conninfo import make_conninfo
from sqlalchemy import JSON, DateTime, MetaData, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from agnostic_kernel.settings import DatabaseSettings
from agnostic_kernel.tls import asyncpg_ssl, libpq_tls_params

SCHEMA = "agnostic"
JOBS_SCHEMA = "procrastinate"
APPLICATION_NAME = "agnostic"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JsonDocument = JSON().with_variant(JSONB(), "postgresql")
"""JSON column type: ``jsonb`` on PostgreSQL, ``JSON`` elsewhere."""


def make_metadata() -> MetaData:
    """Metadata for a module's tables: ``agnostic`` schema and deterministic constraint names."""
    return MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; everything in the control plane is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def aware_or_none(value: datetime | None) -> datetime | None:
    return aware(value) if value is not None else None


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    if settings.backend == "sqlite":
        return _create_sqlite_engine(settings)
    url = make_url(settings.url.get_secret_value()).set(drivername="postgresql+asyncpg", query={})
    return create_async_engine(
        url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
        pool_timeout=settings.pool_timeout,
        pool_recycle=1800,
        connect_args={
            "ssl": asyncpg_ssl(settings.sslmode, settings.tls),
            "timeout": settings.connect_timeout,
            "command_timeout": settings.command_timeout,
            "server_settings": {
                "application_name": APPLICATION_NAME,
                "statement_timeout": str(settings.statement_timeout_ms),
                "idle_in_transaction_session_timeout": "60000",
            },
        },
    )


def _create_sqlite_engine(settings: DatabaseSettings) -> AsyncEngine:
    url = make_url(settings.url.get_secret_value()).set(drivername="sqlite+aiosqlite")
    in_memory = url.database in {None, "", ":memory:"}
    kwargs: dict[str, Any] = {"poolclass": StaticPool} if in_memory else {}
    engine = create_async_engine(
        url,
        echo=settings.echo,
        connect_args={"timeout": settings.connect_timeout},
        execution_options={"schema_translate_map": {SCHEMA: None}},
        **kwargs,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: object) -> None:  # noqa: ANN401  # pyright: ignore[reportUnusedFunction]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if not in_memory:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def is_postgresql(connection: Connection) -> bool:
    return connection.dialect.name == "postgresql"


def psycopg_conninfo(settings: DatabaseSettings, *, search_path: str | None = None) -> str:
    """Libpq connection string for psycopg (PostgreSQL only), carrying TLS options and an optional ``search_path``."""
    if settings.backend != "postgresql":
        msg = "psycopg connections need a PostgreSQL database"
        raise ValueError(msg)
    url = make_url(settings.url.get_secret_value()).set(drivername="postgresql", query={})
    params = libpq_tls_params(settings.sslmode, settings.tls)
    params["application_name"] = APPLICATION_NAME
    params["connect_timeout"] = str(max(1, int(settings.connect_timeout)))
    # TCP keepalives: the worker's LISTEN connection notices a primary that vanished without closing the socket.
    params |= {"keepalives": "1", "keepalives_idle": "10", "keepalives_interval": "5", "keepalives_count": "3"}
    options = [f"-c statement_timeout={settings.statement_timeout_ms}"]
    if search_path:
        options.append(f"-c search_path={search_path}")
    params["options"] = " ".join(options)
    return make_conninfo(url.render_as_string(hide_password=False), **params)
