"""Directory sync.

SCIM tokens, sync status, mapping rules, deprovisioning behaviour and the Google Workspace config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from agnostic_directory.domain.groups import GroupSource

SCIM_TOKEN_ID_PREFIX = "scim"  # noqa: S105  (an id prefix, not a secret)
SCIM_TOKEN_PREFIX = "agn_scim_"  # noqa: S105  (the public token prefix)
SCIM_TOKEN_DISPLAY_PREFIX = 13
"""``agn_scim_`` plus the first four random characters: enough to tell tokens apart in the list."""
ROTATION_GRACE = timedelta(hours=24)
"""After a rotation the previous token keeps working this long (or until revoked), so the IdP can be updated."""
RULE_ID_PREFIX = "dmr"
MAX_LABEL = 60
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/admin.directory.group.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
)
GOOGLE_ACTOR = "Google Workspace"

type RuleSource = Literal["scim", "oidc_claim", "google_directory"]
type DeprovisionBehaviour = Literal["disable", "remove"]
type TokenState = Literal["active", "rotating", "expired", "revoked"]


class InvalidSyncConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScimToken:
    id: str
    label: str
    prefix: str
    token_hash: str
    created_by: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    """Set on the old token when it is rotated: it stops working then."""
    revoked_at: datetime | None
    rotated_from: str | None

    def state(self, now: datetime) -> TokenState:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None:
            return "rotating" if self.expires_at > now else "expired"
        return "active"

    def usable(self, now: datetime) -> bool:
        return self.state(now) in {"active", "rotating"}


def clean_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if not cleaned:
        raise InvalidSyncConfigError('Give the token a label, e.g. the IdP that uses it ("Okta SCIM").')
    if len(cleaned) > MAX_LABEL:
        raise InvalidSyncConfigError(f"Use at most {MAX_LABEL} characters for the label.")
    return cleaned


@dataclass(frozen=True, slots=True)
class ScimUser:
    """The IdP's view of a person: its ``externalId`` for them, their ``userName``, the resource as last sent."""

    user_id: str
    external_id: str | None
    user_name: str
    active: bool
    raw: dict[str, object]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SyncState:
    """What the "Okta SCIM · synced 4 min ago" pill shows."""

    last_request_at: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict[str, int])

    @property
    def healthy(self) -> bool:
        if self.last_error_at is None:
            return True
        return self.last_request_at is not None and self.last_request_at > self.last_error_at


@dataclass(frozen=True, slots=True)
class MappingRule:
    """Members of the IdP group ``idp_group`` (name or id, from ``source``) are also members of ``group_id``.

    ``provider_id`` narrows ``oidc_claim`` rules to one sign-in provider; ``None`` matches any.
    """

    id: str
    source: RuleSource
    provider_id: str | None
    idp_group: str
    group_id: str
    created_by: str
    created_at: datetime

    def matches(self, source: GroupSource, external_id: str | None, external_name: str | None) -> bool:
        if source != self.source:
            return False
        wanted = self.idp_group.strip().lower()
        if self.source == "oidc_claim":
            provider, _, name = (external_id or "").partition(":")
            if self.provider_id is not None and provider != self.provider_id:
                return False
            return wanted in {name.lower(), (external_name or "").lower()}
        return wanted in {(external_id or "").lower(), (external_name or "").lower()}


@dataclass(frozen=True, slots=True)
class SyncSettings:
    """How deprovisioning works when the IdP deactivates someone (SCIM ``active=false``, a suspended Google user).

    Both behaviours set the account to deprovisioned, end its sessions, delete its role bindings and take it out
    of every group. ``disable`` keeps the org membership, so reactivating the person restores their org role;
    ``remove`` also removes them from the org (freeing the seat), and reactivating them joins them again as a
    Member (or through a pending invitation). Deleting a SCIM user always removes the membership.
    """

    deprovision: DeprovisionBehaviour = "disable"


@dataclass(frozen=True, slots=True)
class GoogleCredentials:
    """The secret part of the Google config: a service-account key with domain-wide delegation."""

    client_email: str
    private_key: str
    private_key_id: str | None
    admin_subject: str
    """A Workspace admin the service account acts as (``sub`` of the delegated token)."""
    customer_id: str = "my_customer"


@dataclass(frozen=True, slots=True)
class GoogleRecord:
    """The stored Google Workspace sync: ``config_enc`` is the sealed :class:`GoogleCredentials` (JSON)."""

    config_enc: str | None = None
    group_filter: tuple[str, ...] = ()
    enabled: bool = False
    last_run_at: datetime | None = None
    last_error: str | None = None
    counts: dict[str, int] = field(default_factory=dict[str, int])


def group_selected(group_filter: tuple[str, ...], *, email: str, name: str) -> bool:
    """Which Google groups are synced. An empty filter selects every group.

    Each entry is either a prefix of the group email ending in ``*`` (``eng-*``) or text the group email or name
    contains (``support``), case-insensitively.
    """
    if not group_filter:
        return True
    email, name = email.lower(), name.lower()
    for entry in group_filter:
        wanted = entry.strip().lower()
        if not wanted:
            continue
        if wanted.endswith("*"):
            if email.startswith(wanted[:-1]):
                return True
        elif wanted in email or wanted in name:
            return True
    return False


def clean_group_filter(entries: list[str]) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(entry.strip() for entry in entries if entry.strip()))
    if len(cleaned) > 100:  # noqa: PLR2004
        raise InvalidSyncConfigError("Use at most 100 group filter entries.")
    return cleaned
