"""SQL repository of the scheduler module."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware
from agnostic_scheduler.application.ports import DisableNote
from agnostic_scheduler.infrastructure.tables import NoteRow


class SqlNoteStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def notes(self, instance_id: str, schedule_ids: Sequence[str]) -> dict[str, DisableNote]:
        if not schedule_ids:
            return {}
        query = select(NoteRow).where(NoteRow.instance_id == instance_id, NoteRow.schedule_id.in_(list(schedule_ids)))
        return {
            row.schedule_id: DisableNote(
                instance_id=row.instance_id,
                schedule_id=row.schedule_id,
                reason=row.reason,
                disabled_by=row.disabled_by,
                disabled_by_name=row.disabled_by_name,
                disabled_at=aware(row.disabled_at),
            )
            for row in (await self._session.scalars(query)).all()
        }

    async def set(self, note: DisableNote) -> None:
        row = await self._session.get(NoteRow, (note.instance_id, note.schedule_id))
        if row is None:
            row = NoteRow(instance_id=note.instance_id, schedule_id=note.schedule_id)
            self._session.add(row)
        row.reason = note.reason
        row.disabled_by = note.disabled_by
        row.disabled_by_name = note.disabled_by_name
        row.disabled_at = note.disabled_at
        await self._session.flush()

    async def clear(self, instance_id: str, schedule_id: str) -> None:
        _ = await self._session.execute(
            delete(NoteRow).where(NoteRow.instance_id == instance_id, NoteRow.schedule_id == schedule_id)
        )

    async def commit(self) -> None:
        await self._session.commit()
