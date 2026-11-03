"""Groups of people: made by hand, or synced from an identity provider.

A group carries role bindings (owned by the access module) and can be an approval route target. Members inherit
the group's bindings; owners can additionally approve temporary access to what the group has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

GROUP_ID_PREFIX = "grp"
MAX_GROUP_NAME = 80

type GroupSource = Literal["manual", "scim", "oidc_claim", "google_directory"]
type MemberRole = Literal["member", "owner"]

SOURCE_LABELS: dict[str, str] = {
    "manual": "Manual",
    "scim": "SCIM",
    "oidc_claim": "IdP claim",
    "google_directory": "Google Workspace",
}


class InvalidGroupError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    name: str
    description: str
    source: GroupSource
    external_id: str | None
    external_name: str | None
    created_at: datetime
    updated_at: datetime
    member_count: int = 0

    @property
    def synced(self) -> bool:
        """Membership comes from the IdP; people can't add or remove members by hand."""
        return self.source != "manual"

    def sync_label(self) -> str:
        if not self.synced:
            return SOURCE_LABELS["manual"]
        return f"{SOURCE_LABELS[self.source]} · {self.external_name or self.external_id or self.name}"


@dataclass(frozen=True, slots=True)
class GroupMember:
    group_id: str
    user_id: str
    role: MemberRole
    source: GroupSource
    added_at: datetime
    rule_id: str | None = None
    """Set when a mapping rule put them here (from the IdP group the rule names); the rule also takes them out."""


def clean_group_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise InvalidGroupError("A group needs a name.")
    if len(cleaned) > MAX_GROUP_NAME:
        raise InvalidGroupError(f"Use at most {MAX_GROUP_NAME} characters for the group name.")
    return cleaned


_SLUG = re.compile(r"[^a-z0-9]+")


def group_key(name: str) -> str:
    """Case- and punctuation-insensitive key, so "Support AI" and "support-ai" are the same group."""
    return _SLUG.sub("-", name.lower()).strip("-")


def affects(count: int) -> str:
    return f"Affects {count} member{'s' if count != 1 else ''}"
