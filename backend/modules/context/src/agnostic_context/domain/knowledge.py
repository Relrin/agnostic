"""Knowledge content as the Knowledge page shows it.

A type label per row, filters AgentOS can't apply itself (status, type, text in metadata), status counts, and which
agents and teams read a knowledge base.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

type ContentStatus = Literal["completed", "processing", "partial", "failed"]
STATUSES: tuple[ContentStatus, ...] = ("completed", "processing", "partial", "failed")

_MIME_KINDS: Mapping[str, str] = {
    "text/markdown": "Markdown",
    "text/x-markdown": "Markdown",
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/msword": "DOCX",
    "text/csv": "CSV",
    "application/json": "JSON",
    "application/x-ndjson": "JSON",
    "text/plain": "Text",
    "text/html": "URL",
    "text/uri-list": "URL",
}
_EXTENSION_KINDS: Mapping[str, str] = {
    "md": "Markdown",
    "markdown": "Markdown",
    "pdf": "PDF",
    "docx": "DOCX",
    "doc": "DOCX",
    "csv": "CSV",
    "json": "JSON",
    "jsonl": "JSON",
    "txt": "Text",
}
_REMOTE_KINDS: Mapping[str, str] = {
    "s3": "S3",
    "gcs": "GCS",
    "github": "GitHub",
    "sharepoint": "SharePoint",
    "url": "URL",
    "website": "URL",
    "text": "Text",
}


def content_kind(mime: str | None, name: str | None) -> str:  # noqa: PLR0911
    """A label: "Markdown", "PDF", "DOCX", "CSV", "JSON", "Text", "URL", "S3", "GitHub"… or "Other"."""
    value = (mime or "").split(";", 1)[0].strip().lower()
    if value in _MIME_KINDS:
        return _MIME_KINDS[value]
    if value in _REMOTE_KINDS:
        return _REMOTE_KINDS[value]
    lowered = (name or "").strip().lower()
    if lowered.startswith(("http://", "https://")):
        return "URL"
    if lowered.startswith("s3://"):
        return "S3"
    extension = lowered.rsplit(".", 1)[1] if "." in lowered else ""
    if extension in _EXTENSION_KINDS:
        return _EXTENSION_KINDS[extension]
    if value.startswith("text/"):
        return "Text"
    return "Other"


def _status(row: Mapping[str, Any]) -> str:
    return str(row.get("status") or "completed").lower()


def _haystack(row: Mapping[str, Any]) -> str:
    parts = [str(row.get("name") or ""), str(row.get("description") or "")]
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        parts.extend(f"{key}: {value}" for key, value in metadata.items())  # pyright: ignore[reportUnknownVariableType]
    return "\n".join(parts).lower()


@dataclass(frozen=True, slots=True)
class ContentFilter:
    status: str | None = None
    kind: str | None = None
    search: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.status or self.kind or (self.search and self.search.strip()))

    def matches(self, row: Mapping[str, Any]) -> bool:
        if self.status and _status(row) != self.status.lower():
            return False
        if self.kind and content_kind(row.get("type"), row.get("name")).lower() != self.kind.lower():
            return False
        needle = (self.search or "").strip().lower()
        return not needle or needle in _haystack(row)


@dataclass(frozen=True, slots=True)
class ContentCounts:
    total: int
    by_status: Mapping[str, int]
    by_kind: Mapping[str, int]


def count(rows: Iterable[Mapping[str, Any]]) -> ContentCounts:
    by_status: dict[str, int] = dict.fromkeys(STATUSES, 0)
    by_kind: dict[str, int] = {}
    total = 0
    for row in rows:
        total += 1
        status = _status(row)
        by_status[status] = by_status.get(status, 0) + 1
        kind = content_kind(row.get("type"), row.get("name"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return ContentCounts(total, by_status, dict(sorted(by_kind.items(), key=lambda item: (-item[1], item[0]))))


@dataclass(frozen=True, slots=True)
class KnowledgeReader:
    """An agent or team, and the knowledge contents table it searches (from its ``knowledge`` config)."""

    id: str
    kind: Literal["agent", "team"]
    name: str
    db_id: str | None
    table: str | None


def used_by(db_id: str, table: str, readers: Sequence[KnowledgeReader]) -> list[KnowledgeReader]:
    """Readers of the knowledge base stored in ``table`` of ``db_id`` (the db id is compared when both name one)."""
    return [
        reader
        for reader in readers
        if reader.table == table and (reader.db_id is None or not db_id or reader.db_id == db_id)
    ]
