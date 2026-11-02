"""SQL repositories of the observe module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import orjson
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware, utcnow
from agnostic_kernel.ids import new_id
from agnostic_observe.application.ports import PriceEntry
from agnostic_observe.domain.costs import Price
from agnostic_observe.infrastructure.tables import PriceRow, TraceComparisonRow


class SqlPriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(self, instance_id: str | None) -> list[PriceEntry]:
        scope = PriceRow.instance_id.is_(None) if instance_id is None else PriceRow.instance_id == instance_id
        rows = (await self._session.scalars(select(PriceRow).where(scope).order_by(PriceRow.model_id))).all()
        return [
            PriceEntry(
                price=Price(
                    model_id=row.model_id,
                    provider=row.provider,
                    input_per_1m=row.input_per_1m,
                    output_per_1m=row.output_per_1m,
                    cache_read_per_1m=row.cache_read_per_1m,
                    reasoning_per_1m=row.reasoning_per_1m,
                    currency=row.currency,
                ),
                scope="org" if instance_id is None else "instance",
                updated_at=aware(row.updated_at) if row.updated_at else None,
                updated_by=row.updated_by,
            )
            for row in rows
        ]

    async def replace(self, instance_id: str | None, prices: Sequence[Price], updated_by: str) -> None:
        scope = PriceRow.instance_id.is_(None) if instance_id is None else PriceRow.instance_id == instance_id
        _ = await self._session.execute(delete(PriceRow).where(scope))
        now = utcnow()
        self._session.add_all(
            PriceRow(
                id=new_id("prc"),
                instance_id=instance_id,
                model_id=price.model_id,
                provider=price.provider,
                input_per_1m=price.input_per_1m,
                output_per_1m=price.output_per_1m,
                cache_read_per_1m=price.cache_read_per_1m,
                reasoning_per_1m=price.reasoning_per_1m,
                currency=price.currency,
                updated_by=updated_by,
                updated_at=now,
            )
            for price in prices
        )
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()


class SqlComparisonStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, instance_id: str, trace_id: str, baseline_trace_id: str, *, newer_than: datetime
    ) -> dict[str, Any] | None:
        row = await self._session.get(TraceComparisonRow, (instance_id, trace_id, baseline_trace_id))
        if row is None or aware(row.computed_at) < newer_than:
            return None
        return row.result

    async def put(self, instance_id: str, trace_id: str, baseline_trace_id: str, result: dict[str, Any]) -> None:
        # Round-trip through orjson: datetimes become strings, as they read back from a JSON column.
        document: dict[str, Any] = orjson.loads(orjson.dumps(result))
        row = await self._session.get(TraceComparisonRow, (instance_id, trace_id, baseline_trace_id))
        if row is None:
            self._session.add(
                TraceComparisonRow(
                    instance_id=instance_id,
                    trace_id=trace_id,
                    baseline_trace_id=baseline_trace_id,
                    result=document,
                    computed_at=utcnow(),
                )
            )
        else:
            row.result = document
            row.computed_at = utcnow()
        await self._session.commit()
