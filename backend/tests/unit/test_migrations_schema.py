"""The migrated SQLite schema matches the table models: no table, column, index or type only one of them has."""

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from typer.testing import CliRunner

from agnostic_kernel.modules import discover_modules
from agnostic_kernel.tables import KernelBase
from agnostic_kernel.testing import UNREACHABLE_REDIS
from agnostic_server.cli import app

SQLITE_ONLY_INDEXES = {
    # Unique on SQLite; plain on PostgreSQL, where a unique index on the partitioned table would have to include
    # the partition key. The model declares the plain one.
    "ix_audit_events_source_source_event_id",
}
CROSS_MODULE_FOREIGN_KEYS = {
    # A module's metadata can't name another module's tables, so only the migration declares these.
    ("org_members", "identity_users"),
}


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, sqlite_database: str) -> None:
    monkeypatch.setenv("AGNOSTIC_DATABASE__URL", sqlite_database)
    monkeypatch.setenv("AGNOSTIC_REDIS__URL", UNREACHABLE_REDIS)
    monkeypatch.setenv("AGNOSTIC_LOG__LEVEL", "WARNING")
    monkeypatch.setenv("AGNOSTIC_LOG__FORMAT", "console")


def _no_schema(*_args: object) -> None:
    return None


def _include(_obj: object, name: str | None, type_: str, _reflected: bool, _other: object) -> bool:
    return not (type_ == "table" and name == "alembic_version")


def model_metadata() -> sa.MetaData:
    """Every installed module's tables, moved out of the ``agnostic`` schema as SQLite sees them."""
    target = sa.MetaData()
    sources = [KernelBase.metadata, *(m for module in discover_modules() if (m := module.metadata()) is not None)]
    for source in sources:
        for table in source.tables.values():
            _ = table.to_metadata(
                target,
                schema=None,  # pyright: ignore[reportArgumentType]: SQLAlchemy takes None for "no schema"
                referred_schema_fn=_no_schema,
            )
    return target


def _ignored(diff: tuple[object, ...]) -> bool:
    kind = diff[0]
    if kind in {"add_index", "remove_index"}:
        index = diff[1]
        return isinstance(index, sa.Index) and index.name in SQLITE_ONLY_INDEXES
    if kind == "remove_fk":
        key = diff[1]
        return isinstance(key, sa.ForeignKeyConstraint) and (
            (key.table.name, key.referred_table.name) in CROSS_MODULE_FOREIGN_KEYS
        )
    return False


def _describe(diff: object) -> str:
    if isinstance(diff, list):  # column modifications come as a list of tuples
        return "; ".join(_describe(item) for item in diff)
    assert isinstance(diff, tuple)
    kind, *rest = diff
    target = next((item for item in rest if isinstance(item, (sa.Table, sa.Column, sa.Index))), None)
    name = getattr(target, "name", None) or ".".join(str(item) for item in rest[1:3] if isinstance(item, str))
    table = getattr(target, "table", None)
    return f"{kind} {getattr(table, 'name', '')}.{name}".replace(" .", " ")


def test_migrations_match_models(sqlite_database: str) -> None:
    upgraded = CliRunner().invoke(app, ["db", "upgrade"])
    assert upgraded.exit_code == 0, upgraded.output

    engine = sa.create_engine(sqlite_database)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": _include,
            },
        )
        diffs = compare_metadata(context, model_metadata())
    engine.dispose()

    remaining = [diff for diff in diffs if not (isinstance(diff, tuple) and _ignored(diff))]
    assert not remaining, "migrations and models differ:\n" + "\n".join(_describe(diff) for diff in remaining)
