"""SQLAlchemy persistence for org settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import utcnow
from agnostic_settings.infrastructure.tables import OrgSettingRow


class SqlOrgSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self) -> dict[str, Any]:
        rows = await self._session.scalars(select(OrgSettingRow))
        return {row.key: row.value for row in rows}

    async def store(self, values: Mapping[str, Any], updated_by: str) -> None:
        for key, value in values.items():
            row = await self._session.get(OrgSettingRow, key)
            if row is None:
                self._session.add(OrgSettingRow(key=key, value=value, updated_by=updated_by, updated_at=utcnow()))
            else:
                row.value = value
                row.updated_by = updated_by
                row.updated_at = utcnow()
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
