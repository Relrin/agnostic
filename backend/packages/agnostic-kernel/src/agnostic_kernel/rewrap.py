"""Re-sealing stored secrets with the current master key (``agnostic secrets status`` / ``rotate``).

Modules declare their sealed columns (:class:`~agnostic_kernel.modules.SealedColumn`); this walks them in
primary-key order, in batches, one transaction per batch, so a rotation can be stopped and run again at any point.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import orjson
from sqlalchemy import Column, MetaData, Table, select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.types import Text, TypeEngine

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import SCHEMA, JsonDocument
from agnostic_kernel.modules import SealedColumn

BATCH_SIZE = 500


@dataclass(slots=True)
class ColumnReport:
    column: SealedColumn
    by_key: Counter[str] = field(default_factory=Counter[str])
    """Sealed values per master-key id."""
    resealed: int = 0
    missing_table: bool = False

    @property
    def label(self) -> str:
        keys = f"[{','.join(self.column.json_keys)}]" if self.column.json_keys else ""
        return f"{self.column.table}.{self.column.column}{keys}"


def _values(column_spec: SealedColumn, raw: object) -> list[str]:
    if raw is None:
        return []
    if not column_spec.json_keys:
        return [str(raw)]
    document = _document(raw)
    return [value for key in column_spec.json_keys if isinstance(value := document.get(key), str) and value]


def _document(raw: object) -> dict[str, Any]:
    if isinstance(raw, str | bytes):
        loaded: object = orjson.loads(raw)
        return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}
    return dict(cast("Mapping[str, Any]", raw)) if isinstance(raw, Mapping) else {}


async def _table_exists(engine: AsyncEngine, name: str) -> bool:
    schema = SCHEMA if engine.dialect.name == "postgresql" else None
    async with engine.connect() as connection:
        return await connection.run_sync(lambda sync: sync.dialect.has_table(sync, name, schema=schema))


async def scan(
    engine: AsyncEngine, box: SecretBox, columns: Iterable[SealedColumn], *, reseal: bool = False
) -> list[ColumnReport]:
    """Count sealed values per master key; with ``reseal``, re-seal every value not sealed with the current key."""
    reports: list[ColumnReport] = []
    for spec in columns:
        report = ColumnReport(spec)
        reports.append(report)
        if not await _table_exists(engine, spec.table):
            report.missing_table = True
            continue
        value_type = cast("TypeEngine[Any]", JsonDocument if spec.json_keys else Text())
        # A real Table (not ``table()``): the engine's schema translation only applies to those.
        key_column: Column[Any] = Column(spec.key)
        value_column: Column[Any] = Column(spec.column, value_type)
        target = Table(spec.table, MetaData(), key_column, value_column, schema=SCHEMA)
        key_col, value_col = target.c[spec.key], target.c[spec.column]
        last: object = None
        while True:
            query = select(key_col, value_col).where(value_col.is_not(None)).order_by(key_col).limit(BATCH_SIZE)
            if last is not None:
                query = query.where(key_col > last)
            async with engine.begin() as connection:
                rows = (await connection.execute(query)).all()
                for row_key, raw in rows:
                    changed = False
                    for value in _values(spec, raw):
                        kid = box.sealed_with(value)
                        if kid is None:
                            continue
                        report.by_key[kid] += 1
                        changed = changed or (reseal and kid != box.key_id)
                    if changed:
                        new_value = _resealed(spec, box, raw)
                        _ = await connection.execute(
                            update(target).where(key_col == row_key).values({spec.column: new_value})
                        )
                        report.resealed += 1
            if len(rows) < BATCH_SIZE:
                break
            last = rows[-1][0]
    return reports


def _resealed(spec: SealedColumn, box: SecretBox, raw: object) -> object:
    if not spec.json_keys:
        return box.reseal(str(raw)) or raw
    document = _document(raw)
    for key in spec.json_keys:
        value = document.get(key)
        if isinstance(value, str) and box.sealed_with(value) is not None:
            document[key] = box.reseal(value) or value
    return document
