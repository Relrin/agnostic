"""SQLAlchemy persistence for tool catalog entries and sync state."""

from __future__ import annotations

from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware
from agnostic_tool_catalog.application.ports import SyncState
from agnostic_tool_catalog.domain.entries import Entry, EntryStatus, Kind, Level, Transport
from agnostic_tool_catalog.infrastructure.tables import EntryInstanceRow, EntryRow, SyncStateRow


def _entry(row: EntryRow, instance_ids: tuple[str, ...]) -> Entry:
    return Entry(
        id=row.id,
        slug=row.slug,
        registry_name=row.registry_name,
        level=cast("Level", row.level),
        owner_group_id=row.owner_group_id,
        display_name=row.display_name,
        description=row.description or "",
        icon=row.icon,
        kind=cast("Kind", row.kind),
        transport=cast("Transport | None", row.transport),
        toolkit_key=row.toolkit_key,
        config=dict(row.config or {}),
        requires_confirmation_tools=tuple(row.requires_confirmation_tools or ()),
        instance_ids=instance_ids,
        status=cast("EntryStatus", row.status),
        version=row.version,
        created_by=row.created_by,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
        local=row.local,
    )


def _fill(row: EntryRow, entry: Entry) -> None:
    row.slug = entry.slug
    row.registry_name = entry.registry_name
    row.level = entry.level
    row.owner_group_id = entry.owner_group_id
    row.display_name = entry.display_name
    row.description = entry.description
    row.icon = entry.icon
    row.kind = entry.kind
    row.transport = entry.transport
    row.toolkit_key = entry.toolkit_key
    row.config = entry.config
    row.requires_confirmation_tools = list(entry.requires_confirmation_tools)
    row.local = entry.local
    row.status = entry.status
    row.version = entry.version
    row.created_by = entry.created_by
    row.updated_at = entry.updated_at


class SqlEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _instances(self, entry_ids: list[str] | None = None) -> dict[str, tuple[str, ...]]:
        query = select(EntryInstanceRow)
        if entry_ids is not None:
            query = query.where(EntryInstanceRow.entry_id.in_(entry_ids))
        found: dict[str, list[str]] = {}
        for row in await self._session.scalars(query):
            found.setdefault(row.entry_id, []).append(row.instance_id)
        return {key: tuple(sorted(value)) for key, value in found.items()}

    async def list(self) -> list[Entry]:
        rows = list(await self._session.scalars(select(EntryRow)))
        links = await self._instances()
        return [_entry(row, links.get(row.id, ())) for row in rows]

    async def get(self, entry_id: str) -> Entry | None:
        row = await self._session.get(EntryRow, entry_id)
        if row is None:
            return None
        return _entry(row, (await self._instances([entry_id])).get(entry_id, ()))

    async def by_registry_name(self, name: str) -> Entry | None:
        row = await self._session.scalar(select(EntryRow).where(EntryRow.registry_name == name))
        if row is None:
            return None
        return _entry(row, (await self._instances([row.id])).get(row.id, ()))

    async def add(self, entry: Entry) -> None:
        row = EntryRow(id=entry.id, created_at=entry.created_at)
        _fill(row, entry)
        self._session.add(row)
        await self._session.flush()
        await self._link(entry)

    async def save(self, entry: Entry, *, expected_version: int) -> bool:
        result = await self._session.execute(
            update(EntryRow)
            .where(EntryRow.id == entry.id, EntryRow.version == expected_version)
            .values(
                display_name=entry.display_name,
                description=entry.description,
                icon=entry.icon,
                transport=entry.transport,
                config=entry.config,
                requires_confirmation_tools=list(entry.requires_confirmation_tools),
                local=entry.local,
                status=entry.status,
                version=entry.version,
                updated_at=entry.updated_at,
            )
            .execution_options(synchronize_session="fetch")
        )
        if getattr(result, "rowcount", 0) != 1:
            return False
        await self._link(entry)
        return True

    async def _link(self, entry: Entry) -> None:
        _ = await self._session.execute(delete(EntryInstanceRow).where(EntryInstanceRow.entry_id == entry.id))
        self._session.add_all(EntryInstanceRow(entry_id=entry.id, instance_id=item) for item in entry.instance_ids)
        await self._session.flush()

    async def delete(self, entry_id: str) -> None:
        _ = await self._session.execute(delete(EntryInstanceRow).where(EntryInstanceRow.entry_id == entry_id))
        _ = await self._session.execute(delete(EntryRow).where(EntryRow.id == entry_id))
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()


class SqlSyncStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str) -> SyncState | None:
        row = await self._session.get(SyncStateRow, instance_id)
        if row is None:
            return None
        return SyncState(
            instance_id=row.instance_id,
            manifest_etag=row.manifest_etag,
            entries=row.entries,
            bridge_version=row.bridge_version,
            last_pull_ip=row.last_pull_ip,
            last_pulled_at=aware(row.last_pulled_at) if row.last_pulled_at else None,
        )

    async def record(self, state: SyncState) -> None:
        row = await self._session.get(SyncStateRow, state.instance_id)
        if row is None:
            row = SyncStateRow(instance_id=state.instance_id)
            self._session.add(row)
        row.manifest_etag = state.manifest_etag
        row.entries = state.entries
        row.bridge_version = state.bridge_version
        row.last_pull_ip = state.last_pull_ip
        row.last_pulled_at = state.last_pulled_at
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
