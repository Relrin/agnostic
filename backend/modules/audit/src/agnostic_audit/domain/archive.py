"""Archive tier: months of events written to S3-compatible storage before they leave the database."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agnostic_audit.domain.events import iso_utc, next_month

ARCHIVE_FORMAT = "jsonl+zstd"
MANIFEST_VERSION = 1
RESTORE_DAYS = 7
"""A restored month stays searchable this long, then maintenance drops it again (it is never re-archived)."""

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

type ObjectLockMode = str
"""``off``, ``governance`` or ``compliance``."""


class InvalidMonthError(ValueError):
    pass


def month_key(start: datetime) -> str:
    start = start.astimezone(UTC)
    return f"{start.year:04d}-{start.month:02d}"


def parse_month(key: str) -> datetime:
    """``"2025-08"`` → 2025-08-01T00:00Z."""
    match = _MONTH.fullmatch(key)
    if match is None:
        msg = f"expected a month like 2025-08, got {key!r}"
        raise InvalidMonthError(msg)
    return datetime(int(match.group(1)), int(match.group(2)), 1, tzinfo=UTC)


def month_bounds(key: str) -> tuple[datetime, datetime]:
    start = parse_month(key)
    return start, next_month(start)


def object_keys(prefix: str, month: str) -> tuple[str, str]:
    """``(events key, manifest key)``, side by side under ``prefix``."""
    base = f"{prefix.strip('/')}/" if prefix.strip("/") else ""
    return f"{base}audit-events-{month}.jsonl.zst", f"{base}audit-events-{month}.manifest.json"


@dataclass(frozen=True, slots=True)
class ArchiveTarget:
    """Where archives go: an S3-compatible bucket (credentials already decrypted)."""

    endpoint: str
    bucket: str
    prefix: str
    region: str
    access_key_id: str
    secret_access_key: str
    object_lock_mode: ObjectLockMode = "off"
    retention_days: int | None = None


@dataclass(frozen=True, slots=True)
class Manifest:
    month: str
    event_count: int
    sha256: str
    bytes: int
    chain_head: str | None
    created_at: datetime
    format: str = ARCHIVE_FORMAT
    version: int = MANIFEST_VERSION

    def to_json(self) -> bytes:
        document: dict[str, Any] = {
            "version": self.version,
            "month": self.month,
            "format": self.format,
            "event_count": self.event_count,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "chain_head": self.chain_head,
            "created_at": iso_utc(self.created_at),
        }
        return json.dumps(document, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    @classmethod
    def parse(cls, data: bytes) -> Manifest:
        """Raises ``ValueError`` (or ``KeyError``) for anything that isn't a manifest this version wrote."""
        document = json.loads(data)
        if not isinstance(document, dict):
            raise ValueError("the manifest is not a JSON object")  # noqa: TRY004  (a malformed archive)
        values: dict[str, Any] = document  # pyright: ignore[reportUnknownVariableType]
        if values.get("format") != ARCHIVE_FORMAT:
            msg = f"unknown archive format {values.get('format')!r}"
            raise ValueError(msg)
        return cls(
            month=str(values["month"]),
            event_count=int(values["event_count"]),
            sha256=str(values["sha256"]),
            bytes=int(values["bytes"]),
            chain_head=values.get("chain_head"),
            created_at=datetime.fromisoformat(str(values["created_at"])),
            format=str(values["format"]),
            version=int(values.get("version", MANIFEST_VERSION)),
        )


class ArchiveVerificationError(ValueError):
    """The stored archive doesn't match what was written (or what its manifest says)."""
