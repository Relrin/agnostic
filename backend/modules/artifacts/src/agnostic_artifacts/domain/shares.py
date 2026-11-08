"""Share links: one artefact, pinned to the exact bytes it had when shared, for a while, for an audience.

A link is a random token; only its SHA-256 is stored, so the table cannot be turned back into working links. A share
names one stored object (session, storage key) and its hash: storage keys are never reused, and a file the agent
changes later becomes a new artefact, so a link keeps showing what was shared. Opening checks the hash again.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

type Audience = Literal["org", "link"]
"""``org``: signed-in members of the organization. ``link``: anyone holding the link (when enabled)."""

TOKEN_PREFIX = "ash_"  # noqa: S105  (a prefix that marks share tokens, not a secret)
ID_PREFIX = "shr"
MIN_TTL = timedelta(minutes=5)


class ShareError(ValueError):
    pass


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def looks_like_token(value: str) -> bool:
    return value.startswith(TOKEN_PREFIX) and 30 < len(value) < 80  # noqa: PLR2004


@dataclass(frozen=True, slots=True)
class Share:
    id: str
    instance_id: str
    session_id: str
    storage_key: str
    filename: str
    content_type: str
    size: int
    sha256: str
    audience: Audience
    created_by: str
    created_by_name: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    opened_count: int = 0
    last_opened_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now

    def state(self, now: datetime) -> Literal["active", "expired", "revoked"]:
        if self.revoked_at is not None:
            return "revoked"
        return "active" if self.expires_at > now else "expired"

    def revoked(self, now: datetime) -> Share:
        return self if self.revoked_at is not None else replace(self, revoked_at=now)

    def opened(self, now: datetime) -> Share:
        return replace(self, opened_count=self.opened_count + 1, last_opened_at=now)


def expiry(now: datetime, ttl_seconds: int, *, maximum: timedelta) -> datetime:
    ttl = timedelta(seconds=ttl_seconds)
    if ttl < MIN_TTL:
        raise ShareError("A share link lasts at least five minutes.")
    if ttl > maximum:
        raise ShareError(f"A share link lasts at most {maximum.days} days here.")
    return now + ttl
