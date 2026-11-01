"""Users, passwords and sessions. Pure Python."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

USER_ID_PREFIX = "usr"
MAX_DISPLAY_NAME = 120
MAX_PASSWORD = 1024
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DEPROVISIONED = "deprovisioned"


class CreatedVia(StrEnum):
    LOCAL = "local"
    BOOTSTRAP = "bootstrap"
    INVITE = "invite"
    OIDC = "oidc"


class InvalidEmailError(ValueError):
    pass


class WeakPasswordError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    display_name: str
    avatar_seed: str
    status: UserStatus
    locale: str | None
    timezone: str | None
    created_via: CreatedVia
    created_at: datetime
    last_active_at: datetime | None

    @property
    def active(self) -> bool:
        return self.status is UserStatus.ACTIVE


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.fullmatch(cleaned) or len(cleaned) > 320:  # noqa: PLR2004
        raise InvalidEmailError(f"{email!r} is not an email address.")
    return cleaned


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


def clean_display_name(name: str | None, email: str) -> str:
    cleaned = " ".join((name or "").split())[:MAX_DISPLAY_NAME]
    return cleaned or email.split("@", 1)[0]


def check_password(password: str, *, email: str, min_length: int) -> None:
    """Length is the rule that matters (NIST 800-63B); no composition rules."""
    if len(password) < min_length:
        raise WeakPasswordError(f"Use at least {min_length} characters.")
    if len(password) > MAX_PASSWORD:
        raise WeakPasswordError(f"Use at most {MAX_PASSWORD} characters.")
    if password.strip().lower() in {email, email.split("@", 1)[0]}:
        raise WeakPasswordError("Don't use your email address as your password.")


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    idle: timedelta
    absolute: timedelta

    def ttl(self, now: datetime, created_at: datetime) -> float:
        """Seconds the session stays valid from ``now``: idle timeout, capped by the absolute lifetime."""
        remaining = created_at + self.absolute - now
        return max(0.0, min(self.idle, remaining).total_seconds())


@dataclass(frozen=True, slots=True)
class WebSession:
    key: str
    """Hash of the cookie value (the cookie itself is never stored)."""
    user_id: str
    email: str
    display_name: str
    csrf_token: str
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    method: str
    """How the person signed in: ``password`` or ``sso:<provider>``."""


def safe_next(target: str | None, default: str = "/") -> str:
    """Only same-origin relative paths are allowed as post-login redirects."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    return target
