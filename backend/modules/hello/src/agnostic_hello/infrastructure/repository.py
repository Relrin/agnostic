"""SQLAlchemy implementation of :class:`GreetingRepository`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_hello.domain.greeting import GREETING_ID_PREFIX, Greeting, GreetingStatus
from agnostic_hello.infrastructure.tables import GreetingRow
from agnostic_kernel.db import utcnow
from agnostic_kernel.ids import new_id


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; everything in the control plane is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _to_domain(row: GreetingRow) -> Greeting:
    return Greeting(
        id=row.id,
        message=row.message,
        status=GreetingStatus(row.status),
        reply=row.reply,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


class SqlGreetingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: str) -> Greeting:
        now = utcnow()
        row = GreetingRow(
            id=new_id(GREETING_ID_PREFIX),
            message=message,
            status=GreetingStatus.PENDING.value,
            reply=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_domain(row)

    async def get(self, greeting_id: str) -> Greeting | None:
        row = await self._session.get(GreetingRow, greeting_id, populate_existing=True)
        return _to_domain(row) if row else None

    async def save(self, greeting: Greeting) -> None:
        row = await self._session.get(GreetingRow, greeting.id)
        if row is None:
            return
        row.message = greeting.message
        row.status = greeting.status.value
        row.reply = greeting.reply
        row.updated_at = greeting.updated_at
        await self._session.flush()

    async def list_page(self, limit: int, after_id: str | None) -> Sequence[Greeting]:
        # ULIDs sort by creation time, so the id doubles as a stable cursor (newest first).
        statement = select(GreetingRow).order_by(GreetingRow.id.desc()).limit(limit)
        if after_id is not None:
            statement = statement.where(GreetingRow.id < after_id)
        rows = await self._session.scalars(statement)
        return [_to_domain(row) for row in rows]

    async def count(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(GreetingRow)) or 0)

    async def commit(self) -> None:
        await self._session.commit()
