"""Alembic with one branch per module.

The kernel branch (``kernel``) creates the schema foundations; each module ships its own version directory whose
first revision ``depends_on`` the kernel base. Migrations always cover every *installed* module, including disabled
ones, so turning a module off never strands its revisions in the version table.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel.db import SCHEMA, is_postgresql
from agnostic_kernel.modules import Module
from agnostic_kernel.tables import KernelBase

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
KERNEL_VERSIONS = MIGRATIONS_DIR / "versions"
UNLIMITED_STATEMENTS = "SET LOCAL statement_timeout = 0"
"""Migrations build indexes and rewrite tables: they run without the API's statement timeout."""


@dataclass(frozen=True, slots=True)
class MigrationState:
    current: tuple[str, ...]
    heads: tuple[str, ...]
    pending: tuple[str, ...]

    @property
    def up_to_date(self) -> bool:
        return not self.pending


def alembic_config(modules: Iterable[Module]) -> Config:
    modules = list(modules)
    locations = [str(KERNEL_VERSIONS)]
    metadata: list[MetaData] = [KernelBase.metadata]
    for module in modules:
        location = module.migrations()
        if location is not None:
            locations.append(str(location))
        module_metadata = module.metadata()
        if module_metadata is not None:
            metadata.append(module_metadata)

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", os.pathsep.join(locations))
    config.attributes["metadata"] = metadata
    return config


def script_heads(modules: Iterable[Module]) -> tuple[str, ...]:
    return tuple(sorted(ScriptDirectory.from_config(alembic_config(modules)).get_heads()))


def pending_revisions(script: ScriptDirectory, current: Sequence[str]) -> tuple[str, ...]:
    """Revisions not yet applied.

    Module branches hang off the kernel via ``depends_on``, so the version table can hold fewer rows than there
    are heads; walking the ancestors of what's applied handles that.
    """
    every = {revision.revision for revision in script.walk_revisions()}
    applied: set[str] = (
        {revision.revision for revision in script.iterate_revisions(tuple(current), "base")} if current else set()
    )
    return tuple(sorted(every - applied))


async def _run(engine: AsyncEngine, config: Config, operation: str, *args: object) -> None:
    async with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            _ = await connection.execute(text(UNLIMITED_STATEMENTS))
            _ = await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

        def run(sync_connection: Connection) -> None:
            config.attributes["connection"] = sync_connection
            getattr(command, operation)(config, *args)

        await connection.run_sync(run)


async def upgrade(engine: AsyncEngine, modules: Iterable[Module], revision: str = "heads") -> None:
    await _run(engine, alembic_config(modules), "upgrade", revision)


async def downgrade(engine: AsyncEngine, modules: Iterable[Module], revision: str) -> None:
    await _run(engine, alembic_config(modules), "downgrade", revision)


@dataclass(frozen=True, slots=True)
class AppliedRevision:
    revision: str
    seconds: float


class _DryRunRollback(Exception):  # noqa: N818
    """Raised inside the migration transaction so it rolls back."""


async def check_upgrade(
    engine: AsyncEngine, modules: Iterable[Module], revision: str = "heads"
) -> list[AppliedRevision]:
    """Apply pending migrations inside one transaction, time each revision, then roll everything back.

    Run it against a copy of production data before an upgrade: a migration that fails or locks for long shows up
    here, and the database is left as it was. PostgreSQL only: its DDL is transactional, SQLite's driver commits
    schema changes as they happen.
    """
    config = alembic_config(modules)
    applied: list[AppliedRevision] = []
    started = time.perf_counter()

    def on_version_apply(**kwargs: object) -> None:
        nonlocal started
        step = kwargs.get("step")
        now = time.perf_counter()
        applied.append(AppliedRevision(str(getattr(step, "up_revision_id", step)), now - started))
        started = now

    config.attributes["on_version_apply"] = on_version_apply
    try:
        async with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                _ = await connection.execute(text(UNLIMITED_STATEMENTS))
                _ = await connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

            def run(sync_connection: Connection) -> None:
                config.attributes["connection"] = sync_connection
                command.upgrade(config, revision)
                raise _DryRunRollback  # noqa: TRY301  (the only way out of run_sync that rolls back)

            await connection.run_sync(run)
    except _DryRunRollback:
        pass
    return applied


async def state(engine: AsyncEngine, modules: Sequence[Module]) -> MigrationState:
    async with engine.connect() as connection:

        def current(sync_connection: Connection) -> tuple[str, ...]:
            schema = SCHEMA if is_postgresql(sync_connection) else None
            context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
            return tuple(sorted(context.get_current_heads()))

        applied = await connection.run_sync(current)
    script = ScriptDirectory.from_config(alembic_config(modules))
    return MigrationState(
        current=applied,
        heads=tuple(sorted(script.get_heads())),
        pending=pending_revisions(script, applied),
    )
