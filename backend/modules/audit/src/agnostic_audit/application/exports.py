"""Exporting the log.

A synchronous download for small ranges, a background job (zstd-compressed, kept 24 h) for large ones.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator, Mapping
from compression import zstd
from datetime import datetime
from http import HTTPStatus
from typing import Any

from agnostic_audit.application.ports import (
    AuditRepository,
    EventQuery,
    ExportRepository,
    Jobs,
    Position,
    UnitOfWork,
)
from agnostic_audit.application.views import query_from_filters
from agnostic_audit.domain.events import AuditEvent, event_document, iso_utc
from agnostic_audit.domain.governance import (
    CSV_COLUMNS,
    EXPORT_ID_PREFIX,
    EXPORT_TTL,
    ExportFormat,
    ExportJob,
    clean_filters,
)
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import AppError, NotFoundError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

EXPORT_TASK = "audit.export"
PAGE = 1000
MEDIA_TYPES: Mapping[str, str] = {"csv": "text/csv; charset=utf-8", "jsonl": "application/x-ndjson"}
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportTooLargeError(AppError):
    status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    code = "export_too_large"
    title = "Too many events to download at once"


def _cell(value: object) -> str:
    """Spreadsheet-safe text: values that would start a formula get a leading apostrophe."""
    if value is None:
        return ""
    text = ", ".join(value) if isinstance(value, (list, tuple)) else str(value)  # pyright: ignore[reportUnknownArgumentType]
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _csv_row(values: Iterable[object]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow([_cell(value) for value in values])
    return buffer.getvalue()


def csv_header() -> str:
    return _csv_row(CSV_COLUMNS)


def csv_line(event: AuditEvent) -> str:
    values: dict[str, Any] = {
        **event_document(event),
        "occurred_at": iso_utc(event.occurred_at),
        "actor_kind": event.actor.kind,
        "actor_id": event.actor.id,
        "actor_display": event.actor.display,
    }
    return _csv_row(values.get(column) for column in CSV_COLUMNS)


def jsonl_line(event: AuditEvent) -> str:
    return json.dumps(event_document(event), ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def render(events: Iterable[AuditEvent], export_format: ExportFormat) -> Iterator[str]:
    if export_format == "csv":
        yield csv_header()
        for event in events:
            yield csv_line(event)
    else:
        for event in events:
            yield jsonl_line(event)


def filename(export_format: ExportFormat, at: datetime) -> str:
    return f"audit-events-{at.strftime('%Y%m%d-%H%M%S')}.{export_format}"


class Exports:
    def __init__(
        self, events: AuditRepository, exports: ExportRepository, uow: UnitOfWork, jobs: Jobs, sync_limit: int
    ) -> None:
        self._events = events
        self._exports = exports
        self._uow = uow
        self._jobs = jobs
        self._sync_limit = sync_limit

    async def _all(self, query: EventQuery, limit: int | None = None) -> list[AuditEvent]:
        found: list[AuditEvent] = []
        after: Position | None = None
        while limit is None or len(found) < limit:
            page = list(await self._events.list_page(query, PAGE, after))
            found.extend(page)
            if len(page) < PAGE:
                break
            after = (page[-1].occurred_at, page[-1].id)
        return found if limit is None else found[:limit]

    async def sync(self, query: EventQuery) -> list[AuditEvent]:
        """Up to the sync limit, newest first; larger ranges raise :class:`ExportTooLargeError`."""
        if await self._events.count(query, self._sync_limit + 1) > self._sync_limit:
            raise ExportTooLargeError(
                f"This range has more than {self._sync_limit:,} events. Narrow the filters, or start a background "
                "export (POST /api/v1/audit/exports) and download it when it's ready.",
                extra={"limit": self._sync_limit, "async_export": "/api/v1/audit/exports"},
            )
        return await self._all(query, self._sync_limit)

    async def request(self, requested_by: str, export_format: ExportFormat, filters: Mapping[str, Any]) -> ExportJob:
        cleaned = clean_filters(filters)
        _ = query_from_filters(cleaned)
        now = utcnow()
        job = ExportJob(
            id=new_id(EXPORT_ID_PREFIX),
            requested_by=requested_by,
            filters=cleaned,
            format=export_format,
            status="queued",
            row_count=None,
            size_bytes=None,
            error=None,
            created_at=now,
            expires_at=now + EXPORT_TTL,
        )
        await self._exports.add(job)
        await self._uow.commit()
        await self._jobs.defer(EXPORT_TASK, export_id=job.id)
        return job

    async def run(self, export_id: str) -> None:
        job = await self._exports.get(export_id)
        if job is None or job.status not in {"queued", "running"}:
            return
        await self._exports.set_status(export_id, "running")
        await self._uow.commit()
        try:
            compressor = zstd.ZstdCompressor()
            chunks: list[bytes] = []
            rows = 0
            if job.format == "csv":
                chunks.append(compressor.compress(csv_header().encode()))
            query = query_from_filters(job.filters)
            after: Position | None = None
            while True:
                page = list(await self._events.list_page(query, PAGE, after))
                for event in page:
                    line = csv_line(event) if job.format == "csv" else jsonl_line(event)
                    chunks.append(compressor.compress(line.encode()))
                rows += len(page)
                if len(page) < PAGE:
                    break
                after = (page[-1].occurred_at, page[-1].id)
            chunks.append(compressor.flush())
            await self._exports.set_status(export_id, "done", content=b"".join(chunks), row_count=rows)
        except Exception as exc:  # noqa: BLE001  (any failure is reported on the export, not lost in the worker)
            log.warning("audit.export_failed", export_id=export_id, error=str(exc))
            await self._uow.rollback()
            await self._exports.set_status(export_id, "failed", error=str(exc) or type(exc).__name__)
        await self._uow.commit()

    async def mine(self, requested_by: str) -> list[ExportJob]:
        return await self._exports.by_requester(requested_by, utcnow())

    async def get(self, requested_by: str, export_id: str) -> ExportJob:
        job = await self._exports.get(export_id)
        if job is None or job.requested_by != requested_by or job.expires_at <= utcnow():
            raise NotFoundError(f"Export {export_id} doesn't exist or has expired.")
        return job

    async def download(self, requested_by: str, export_id: str) -> tuple[ExportJob, bytes]:
        """The finished export, still zstd-compressed."""
        job = await self.get(requested_by, export_id)
        content = await self._exports.content(export_id) if job.status == "done" else None
        if content is None:
            raise NotFoundError(f"Export {export_id} isn't ready yet ({job.status}).")
        return job, content

    async def cleanup(self) -> int:
        removed = await self._exports.delete_expired(utcnow())
        await self._uow.commit()
        return removed


def decompressed_chunks(content: bytes, size: int = 64 * 1024) -> Iterator[bytes]:
    """Decompress a stored export piece by piece while it streams to the browser."""
    decompressor = zstd.ZstdDecompressor()
    for start in range(0, len(content), size):
        chunk = decompressor.decompress(content[start : start + size])
        if chunk:
            yield chunk
