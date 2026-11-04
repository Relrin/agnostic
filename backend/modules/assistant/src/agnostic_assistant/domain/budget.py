"""Monthly token budgets: the org's, and each person's."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CHARS_PER_TOKEN = 4
"""Rough size of a token, for models that don't report usage (some local servers)."""


def month_of(moment: datetime) -> str:
    """Budgets reset on the first of the month, UTC: ``"2026-11"``."""
    return f"{moment.year:04d}-{moment.month:02d}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN) if text else 0


@dataclass(frozen=True, slots=True)
class Spend:
    org_tokens: int
    user_tokens: int


def over_budget(spend: Spend, *, org_limit: int | None, user_limit: int | None) -> str | None:
    """Why another request may not run this month, or ``None``."""
    if org_limit is not None and spend.org_tokens >= org_limit:
        return f"The organization used its {org_limit:,} AI tokens for this month."
    if user_limit is not None and spend.user_tokens >= user_limit:
        return f"You used your {user_limit:,} AI tokens for this month."
    return None
