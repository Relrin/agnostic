"""Alembic environment shared by the kernel and every module branch.

The runner (:mod:`agnostic_kernel.migrations_runner`) passes an open connection and the combined metadata in
``config.attributes``; there is no ``alembic.ini``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, MetaData
from sqlalchemy.sql.schema import SchemaItem

from agnostic_kernel.db import SCHEMA, is_postgresql

config = context.config
connection: Connection = config.attributes["connection"]
target_metadata: list[MetaData] = config.attributes.get("metadata", [])


def include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    if type_ == "schema":
        return name == SCHEMA
    return True


def include_object(_obj: SchemaItem, name: str | None, type_: str, _reflected: bool, _compare_to: object) -> bool:
    return not (type_ == "table" and name == "alembic_version")


postgresql = is_postgresql(connection)
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    version_table_schema=SCHEMA if postgresql else None,
    include_schemas=postgresql,
    render_as_batch=not postgresql,
    include_name=include_name,
    include_object=include_object,
    compare_type=True,
    on_version_apply=config.attributes.get("on_version_apply"),
)

with context.begin_transaction():
    context.run_migrations()
