"""SQLAlchemy persistence for saved views, exports, the policy row, archives, SIEM sinks and ingestion cursors."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

import orjson
from sqlalchemy import RowMapping, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_audit.application.ports import Position
from agnostic_audit.domain.governance import ArchivedMonth, ExportFormat, ExportJob, ExportStatus, SavedView
from agnostic_audit.domain.siem import Sink, SinkFormat, SinkKind, SinkStatus
from agnostic_audit.infrastructure.tables import (
    ArchiveRow,
    ExportRow,
    IngestCursorRow,
    PolicyRow,
    SavedViewRow,
    SinkCursorRow,
    SinkRow,
)
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import aware, aware_or_none

POLICY_ROW_ID = 1


class SqlUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SqlPolicyStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self) -> tuple[dict[str, Any], str | None] | None:
        row = await self._session.get(PolicyRow, POLICY_ROW_ID, populate_existing=True)
        if row is None:
            return None
        values = {column.key: getattr(row, column.key) for column in PolicyRow.__table__.columns}
        secret = values.pop("secret_enc")
        return values, secret

    async def save(self, values: Mapping[str, Any], secret_enc: str | None) -> None:
        row = await self._session.get(PolicyRow, POLICY_ROW_ID)
        if row is None:
            row = PolicyRow(id=POLICY_ROW_ID)
            self._session.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        row.secret_enc = secret_enc
        await self._session.flush()

    async def record_archive_run(self, at: datetime, error: str | None) -> None:
        row = await self._session.get(PolicyRow, POLICY_ROW_ID)
        if row is None:
            row = PolicyRow(id=POLICY_ROW_ID)
            self._session.add(row)
        row.last_archive_at = at
        row.last_archive_error = error
        await self._session.flush()


def _view(row: SavedViewRow) -> SavedView:
    return SavedView(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        filters={str(key): str(value) for key, value in (row.filters or {}).items()},
        position=row.position,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
    )


class SqlViewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def visible_to(self, owner_id: str) -> list[SavedView]:
        rows = await self._session.scalars(
            select(SavedViewRow)
            .where(or_(SavedViewRow.owner_id == owner_id, SavedViewRow.owner_id.is_(None)))
            .order_by(SavedViewRow.position, SavedViewRow.name, SavedViewRow.id)
        )
        return [_view(row) for row in rows]

    async def get(self, view_id: str) -> SavedView | None:
        row = await self._session.get(SavedViewRow, view_id)
        return _view(row) if row else None

    async def save(self, view: SavedView) -> None:
        row = await self._session.get(SavedViewRow, view.id)
        if row is None:
            row = SavedViewRow(id=view.id, created_at=view.created_at)
            self._session.add(row)
        row.owner_id = view.owner_id
        row.name = view.name
        row.filters = dict(view.filters)
        row.position = view.position
        row.updated_at = view.updated_at
        await self._session.flush()

    async def delete(self, view_id: str) -> None:
        _ = await self._session.execute(delete(SavedViewRow).where(SavedViewRow.id == view_id))


def _export(row: RowMapping) -> ExportJob:
    filters: Mapping[str, Any] = row["filters"] or {}
    return ExportJob(
        id=row["id"],
        requested_by=row["requested_by"],
        filters={str(key): str(value) for key, value in filters.items()},
        format=cast("ExportFormat", row["format"]),
        status=cast("ExportStatus", row["status"]),
        row_count=row["row_count"],
        size_bytes=row["size_bytes"],
        error=row["error"],
        created_at=aware(row["created_at"]),
        expires_at=aware(row["expires_at"]),
    )


_EXPORT_COLUMNS = (
    ExportRow.id,
    ExportRow.requested_by,
    ExportRow.filters,
    ExportRow.format,
    ExportRow.status,
    ExportRow.row_count,
    ExportRow.size_bytes,
    ExportRow.error,
    ExportRow.created_at,
    ExportRow.expires_at,
)


class SqlExportRepository:
    """Export rows without their content, unless asked for it (the blob can be large)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: ExportJob) -> None:
        self._session.add(
            ExportRow(
                id=job.id,
                requested_by=job.requested_by,
                filters=dict(job.filters),
                format=job.format,
                status=job.status,
                created_at=job.created_at,
                expires_at=job.expires_at,
            )
        )
        await self._session.flush()

    async def get(self, export_id: str) -> ExportJob | None:
        row = (
            (await self._session.execute(select(*_EXPORT_COLUMNS).where(ExportRow.id == export_id))).mappings().first()
        )
        return _export(row) if row else None

    async def by_requester(self, requested_by: str, now: datetime) -> list[ExportJob]:
        rows = await self._session.execute(
            select(*_EXPORT_COLUMNS)
            .where(ExportRow.requested_by == requested_by, ExportRow.expires_at > now)
            .order_by(ExportRow.created_at.desc())
        )
        return [_export(row) for row in rows.mappings()]

    async def set_status(
        self,
        export_id: str,
        status: ExportStatus,
        *,
        content: bytes | None = None,
        row_count: int | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status, "error": error}
        if content is not None:
            values |= {"content": content, "size_bytes": len(content)}
        if row_count is not None:
            values["row_count"] = row_count
        _ = await self._session.execute(update(ExportRow).where(ExportRow.id == export_id).values(**values))

    async def content(self, export_id: str) -> bytes | None:
        return await self._session.scalar(select(ExportRow.content).where(ExportRow.id == export_id))

    async def delete_expired(self, now: datetime) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(ExportRow).where(ExportRow.expires_at <= now)
        )
        _ = await self._session.execute(delete(ExportRow).where(ExportRow.expires_at <= now))
        return int(count or 0)


def _archive(row: ArchiveRow) -> ArchivedMonth:
    return ArchivedMonth(
        month=row.month,
        object_key=row.object_key,
        manifest_key=row.manifest_key,
        bytes=row.bytes,
        event_count=row.event_count,
        sha256=row.sha256,
        chain_head=row.chain_head,
        archived_at=aware(row.archived_at),
        purge_after=aware_or_none(row.purge_after),
        restored_at=aware_or_none(row.restored_at),
        restore_expires_at=aware_or_none(row.restore_expires_at),
    )


class SqlArchiveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[ArchivedMonth]:
        rows = await self._session.scalars(select(ArchiveRow).order_by(ArchiveRow.month.desc()))
        return [_archive(row) for row in rows]

    async def get(self, month: str) -> ArchivedMonth | None:
        row = await self._session.get(ArchiveRow, month, populate_existing=True)
        return _archive(row) if row else None

    async def save(self, archive: ArchivedMonth) -> None:
        row = await self._session.get(ArchiveRow, archive.month)
        if row is None:
            row = ArchiveRow(month=archive.month)
            self._session.add(row)
        row.object_key = archive.object_key
        row.manifest_key = archive.manifest_key
        row.bytes = archive.bytes
        row.event_count = archive.event_count
        row.sha256 = archive.sha256
        row.chain_head = archive.chain_head
        row.archived_at = archive.archived_at
        row.purge_after = archive.purge_after
        row.restored_at = archive.restored_at
        row.restore_expires_at = archive.restore_expires_at
        await self._session.flush()


class SqlSinkRepository:
    """Sinks with their config sealed by the secret box (it carries webhook secrets and auth headers)."""

    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    def _sink(self, row: SinkRow) -> Sink:
        config: dict[str, Any] = orjson.loads(self._box.open(row.config_enc))
        return Sink(
            id=row.id,
            name=row.name,
            kind=cast("SinkKind", row.kind),
            format=cast("SinkFormat", row.format),
            config=config,
            enabled=row.enabled,
            status=cast("SinkStatus", row.status),
            failure_count=row.failure_count,
            last_event_at=aware_or_none(row.last_event_at),
            last_error=row.last_error,
            created_by=row.created_by,
            created_at=aware(row.created_at),
        )

    async def list(self) -> list[Sink]:
        rows = await self._session.scalars(
            select(SinkRow).order_by(SinkRow.created_at, SinkRow.id).execution_options(populate_existing=True)
        )
        return [self._sink(row) for row in rows]

    async def get(self, sink_id: str) -> Sink | None:
        row = await self._session.get(SinkRow, sink_id, populate_existing=True)
        return self._sink(row) if row else None

    async def save(self, sink: Sink) -> None:
        row = await self._session.get(SinkRow, sink.id)
        if row is None:
            row = SinkRow(id=sink.id, created_by=sink.created_by, created_at=sink.created_at)
            self._session.add(row)
        row.name = sink.name
        row.kind = sink.kind
        row.format = sink.format
        row.config_enc = self._box.seal(orjson.dumps(dict(sink.config)))
        row.enabled = sink.enabled
        row.status = sink.status
        row.failure_count = sink.failure_count
        row.last_event_at = sink.last_event_at
        row.last_error = sink.last_error
        await self._session.flush()

    async def delete(self, sink_id: str) -> None:
        _ = await self._session.execute(delete(SinkCursorRow).where(SinkCursorRow.sink_id == sink_id))
        _ = await self._session.execute(delete(SinkRow).where(SinkRow.id == sink_id))

    async def cursor(self, sink_id: str) -> Position | None:
        row = await self._session.get(SinkCursorRow, sink_id, populate_existing=True)
        return (aware(row.last_occurred_at), row.last_event_id) if row else None

    async def set_cursor(self, sink_id: str, position: Position) -> None:
        row = await self._session.get(SinkCursorRow, sink_id)
        if row is None:
            row = SinkCursorRow(sink_id=sink_id)
            self._session.add(row)
        row.last_occurred_at, row.last_event_id = position
        await self._session.flush()

    async def record_delivery(
        self,
        sink_id: str,
        *,
        status: SinkStatus,
        failure_count: int,
        last_error: str | None,
        last_event_at: datetime | None,
    ) -> None:
        _ = await self._session.execute(
            update(SinkRow)
            .where(SinkRow.id == sink_id)
            .values(status=status, failure_count=failure_count, last_error=last_error, last_event_at=last_event_at)
        )


class SqlIngestCursorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, instance_id: str, stream: str) -> str | None:
        row = await self._session.get(IngestCursorRow, (instance_id, stream), populate_existing=True)
        return row.cursor if row else None

    async def set(self, instance_id: str, stream: str, cursor: str | None, at: datetime) -> None:
        row = await self._session.get(IngestCursorRow, (instance_id, stream))
        if row is None:
            row = IngestCursorRow(instance_id=instance_id, stream=stream)
            self._session.add(row)
        row.cursor = cursor
        row.last_ingested_at = at
        await self._session.flush()


async def any_enabled_sink(session: AsyncSession) -> bool:
    return (await session.scalar(select(SinkRow.id).where(SinkRow.enabled.is_(True)).limit(1))) is not None
