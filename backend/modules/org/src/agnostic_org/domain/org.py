"""The org, its members and invitations. Pure Python.

One org per installation. Org roles govern the control plane; access to AgentOS instances comes
from access-role bindings, plus the implicit full access Owners and Administrators have unless the org requires
explicit bindings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

INVITATION_ID_PREFIX = "inv"
MAX_ORG_NAME = 80


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"


class MemberStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class OrgRuleError(ValueError):
    """A change that the org-role rules don't allow; the message says why."""


@dataclass(frozen=True, slots=True)
class OrgProfile:
    name: str
    slug: str
    logo_url: str | None
    plan_label: str | None
    seat_limit: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Member:
    user_id: str
    org_role: OrgRole
    status: MemberStatus
    joined_at: datetime
    joined_via: str

    @property
    def active(self) -> bool:
        return self.status is MemberStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class InitialBinding:
    """An access-role binding granted when the invitation is accepted (``instance_id=None`` means all)."""

    role_id: str
    instance_id: str | None


@dataclass(frozen=True, slots=True)
class Invitation:
    id: str
    email: str
    org_role: OrgRole
    bindings: tuple[InitialBinding, ...]
    access_ends_at: datetime | None
    invited_by: str
    expires_at: datetime
    status: InvitationStatus
    created_at: datetime
    group_ids: tuple[str, ...] = ()
    """Manual groups the person joins on acceptance."""

    def usable(self, now: datetime) -> bool:
        return self.status is InvitationStatus.PENDING and self.expires_at > now


def clean_org_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise OrgRuleError("The org needs a name.")
    if len(cleaned) > MAX_ORG_NAME:
        raise OrgRuleError(f"Keep the org name under {MAX_ORG_NAME} characters.")
    return cleaned


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:63] or "org"


def check_role_change(*, actor: OrgRole, current: OrgRole, new: OrgRole, owners: int) -> None:
    """Owners manage everyone; Administrators manage Administrators and Members; the last Owner stays."""
    if OrgRole.OWNER in {current, new} and actor is not OrgRole.OWNER:
        raise OrgRuleError("Only an Owner can make someone an Owner or change an Owner's role.")
    if current is OrgRole.OWNER and new is not OrgRole.OWNER and owners <= 1:
        raise OrgRuleError("The org needs at least one Owner. Make someone else an Owner first.")


def check_removal(*, actor: OrgRole, target: OrgRole, owners: int, self_removal: bool) -> None:
    if target is OrgRole.OWNER and actor is not OrgRole.OWNER:
        raise OrgRuleError("Only an Owner can remove an Owner.")
    if target is OrgRole.OWNER and owners <= 1:
        raise OrgRuleError("You can't remove the last Owner.")
    if self_removal and target is OrgRole.OWNER and owners <= 1:
        raise OrgRuleError("You're the last Owner; transfer ownership first.")


def check_invite_role(*, actor: OrgRole, role: OrgRole) -> None:
    if role is OrgRole.OWNER and actor is not OrgRole.OWNER:
        raise OrgRuleError("Only an Owner can invite another Owner.")


def seats_left(seat_limit: int | None, used: int) -> int | None:
    return None if seat_limit is None else max(0, seat_limit - used)
