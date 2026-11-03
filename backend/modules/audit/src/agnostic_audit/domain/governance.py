"""Records around the event log: retention and archive policy, saved views, exports, archives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

type ExportFormat = Literal["csv", "jsonl"]
type ExportStatus = Literal["queued", "running", "done", "failed"]
type ObjectLock = Literal["off", "governance", "compliance"]

VIEW_ID_PREFIX = "avw"
EXPORT_ID_PREFIX = "aexp"
SINK_ID_PREFIX = "sink"
DEFAULT_HOT_RETENTION_DAYS = 400
EXPORT_TTL = timedelta(hours=24)
VIEW_COUNT_CAP = 1000

FILTER_KEYS = ("q", "actor", "actor_kind", "action", "decision", "instance", "resource", "source", "since", "until")
"""What a saved view or an export may filter on (the same names as the event list's query parameters)."""

CSV_COLUMNS = (
    "id",
    "occurred_at",
    "actor_kind",
    "actor_id",
    "actor_display",
    "via",
    "action",
    "resource_kind",
    "resource_id",
    "resource_display",
    "instance_id",
    "decision",
    "scope_checked",
    "missing_scopes",
    "response_status",
    "summary",
    "denial_reason",
    "request_id",
    "ip",
    "client",
    "source",
)


def clean_filters(filters: Mapping[str, Any]) -> dict[str, str]:
    """Known filter keys with non-empty values, as text; anything else is dropped."""
    return {key: str(filters[key]) for key in FILTER_KEYS if filters.get(key) not in (None, "")}


@dataclass(frozen=True, slots=True)
class Policy:
    hot_retention_days: int = DEFAULT_HOT_RETENTION_DAYS
    archive_enabled: bool = False
    endpoint: str | None = None
    bucket: str | None = None
    prefix: str = ""
    region: str = "us-east-1"
    access_key_id: str | None = None
    has_secret: bool = False
    object_lock_mode: ObjectLock = "off"
    archive_retention_days: int | None = None
    """``None``: archives never expire."""
    hash_chain: bool = False
    updated_by: str | None = None
    updated_at: datetime | None = None
    last_archive_at: datetime | None = None
    last_archive_error: str | None = None

    @property
    def archive_ready(self) -> bool:
        return bool(self.archive_enabled and self.endpoint and self.bucket and self.access_key_id and self.has_secret)


@dataclass(frozen=True, slots=True)
class SavedView:
    id: str
    owner_id: str | None
    """``None``: shared with everyone who can read the audit log."""
    name: str
    filters: Mapping[str, str]
    position: int
    created_at: datetime
    updated_at: datetime

    @property
    def shared(self) -> bool:
        return self.owner_id is None


@dataclass(frozen=True, slots=True)
class ExportJob:
    id: str
    requested_by: str
    filters: Mapping[str, str]
    format: ExportFormat
    status: ExportStatus
    row_count: int | None
    size_bytes: int | None
    error: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ArchivedMonth:
    month: str
    object_key: str
    manifest_key: str
    bytes: int
    event_count: int
    sha256: str
    chain_head: str | None
    archived_at: datetime
    purge_after: datetime | None
    restored_at: datetime | None
    restore_expires_at: datetime | None

    def restored(self, now: datetime) -> bool:
        return self.restore_expires_at is not None and self.restore_expires_at > now
