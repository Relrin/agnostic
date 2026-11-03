"""Service accounts: org-level machine identities and their tokens.

An account (``sa:<name>``) holds scopes on one or more instances. It authenticates with two kinds of tokens:

- **native** (``agno_pat_…``): created per instance through AgentOS ``/service-accounts`` and validated by that
  runtime. AgentOS has no rotate call, so rotating one revokes it and creates a new one under the same name
  (callers see a brief gap).
- **gateway** (``agn_pat_…``): issued here and validated by the gateway, which mints a per-instance JWT for each
  call. Rotating one issues a new token and keeps the old one valid for 24 hours so callers can switch.

Only hashes of gateway tokens are stored (sha256 of a pepper and the token); a prefix is kept for display.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

ACCOUNT_ID_PREFIX = "sac"
NATIVE_TOKEN_ID_PREFIX = "snt"  # noqa: S105  (id prefixes, not secrets)
GATEWAY_TOKEN_ID_PREFIX = "sgt"  # noqa: S105

PRINCIPAL_PREFIX = "sa:"
SUBJECT_PREFIX = "svc_"
"""AgentOS rejects JWT subjects starting with ``sa:``, so gateway calls run as ``svc_<name>``."""

GATEWAY_TOKEN_PREFIX = "agn_pat_"  # noqa: S105  (token formats)
NATIVE_TOKEN_PREFIX = "agno_pat_"  # noqa: S105
DISPLAY_PREFIX_LENGTH = 12
"""``agn_pat_`` and four characters: enough to tell tokens apart, useless for guessing them."""

MAX_NAME = 63
NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
ROTATION_GRACE = timedelta(hours=24)
EXPIRY_WARNING = timedelta(days=14)

type ScopeSource = Literal["role", "custom"]
type TokenStatus = Literal["active", "revoked", "expired"]
type TokenKind = Literal["native", "gateway"]
type ExpiresIn = Literal["30d", "90d", "365d", "never"]

EXPIRY_CHOICES: dict[str, int | None] = {"30d": 30, "90d": 90, "365d": 365, "never": None}
DEFAULT_EXPIRY: ExpiresIn = "90d"
ADMIN_SCOPE = "agent_os:admin"


class InvalidServiceAccountError(ValueError):
    pass


def check_name(name: str) -> str:
    """A lowercase slug (letters, digits, dashes), at most 63 characters, like AgentOS requires."""
    cleaned = name.strip()
    if not cleaned:
        raise InvalidServiceAccountError("Give the service account a name.")
    if len(cleaned) > MAX_NAME:
        raise InvalidServiceAccountError(f"The name can be at most {MAX_NAME} characters.")
    if not NAME_PATTERN.fullmatch(cleaned):
        raise InvalidServiceAccountError(
            "Use lowercase letters, digits and dashes, starting and ending with a letter or digit (airflow-nightly)."
        )
    return cleaned


def principal_of(name: str) -> str:
    return f"{PRINCIPAL_PREFIX}{name}"


def subject_of(name: str) -> str:
    """The JWT ``sub`` the gateway mints for the account."""
    return f"{SUBJECT_PREFIX}{name}"


def expiry_days(choice: str) -> int | None:
    if choice not in EXPIRY_CHOICES:
        raise InvalidServiceAccountError(f"Expiry must be one of {', '.join(EXPIRY_CHOICES)}, not {choice!r}.")
    return EXPIRY_CHOICES[choice]


def expires_at(choice: str, now: datetime) -> datetime | None:
    days = expiry_days(choice)
    return now + timedelta(days=days) if days is not None else None


def is_privileged(scope: str) -> bool:
    """Write and delete scopes, ``agent_os:admin`` and any ``service_accounts:*`` need explicit confirmation."""
    parts = scope.split(":")
    return scope == ADMIN_SCOPE or parts[0] == "service_accounts" or parts[-1] in {"write", "delete"}


def privileged_scopes(scopes: tuple[str, ...] | list[str] | frozenset[str]) -> list[str]:
    return sorted(scope for scope in set(scopes) if is_privileged(scope))


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    id: str
    name: str
    description: str
    scope_source: ScopeSource
    role_id: str | None
    scopes: tuple[str, ...]
    """Scopes granted directly: the custom checklist, or the extras on top of the role."""
    instance_ids: tuple[str, ...]
    forwards_user_id: bool
    created_by: str
    created_by_name: str
    created_at: datetime
    expires_at: datetime | None
    deleted_at: datetime | None = None

    @property
    def principal(self) -> str:
        return principal_of(self.name)

    @property
    def subject(self) -> str:
        return subject_of(self.name)

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def expired(self, now: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= now

    def usable(self, now: datetime) -> bool:
        return not self.deleted and not self.expired(now)

    def expiry_warning(self, now: datetime) -> bool:
        """Amber in the list: no expiry at all, or less than two weeks left."""
        return self.expires_at is None or self.expires_at - now < EXPIRY_WARNING

    def delete(self, at: datetime) -> ServiceAccount:
        return replace(self, deleted_at=at)


@dataclass(frozen=True, slots=True)
class NativeToken:
    """An ``agno_pat_`` token of one instance; AgentOS keeps the hash, this keeps what the UI shows."""

    id: str
    account_id: str
    instance_id: str
    agentos_sa_id: str
    token_prefix: str
    status: TokenStatus
    scopes: tuple[str, ...]
    created_at: datetime
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"

    def revoke(self, at: datetime) -> NativeToken:
        if not self.active:
            return self
        return replace(self, status="revoked", revoked_at=at)

    def observed(
        self, *, last_used_at: datetime | None, revoked_at: datetime | None, expires_at: datetime | None, now: datetime
    ) -> NativeToken:
        """Apply what the instance reports (the last-used poll)."""
        status: TokenStatus = self.status
        if revoked_at is not None and status == "active":
            status = "revoked"
        elif expires_at is not None and expires_at <= now and status == "active":
            status = "expired"
        return replace(
            self,
            status=status,
            revoked_at=self.revoked_at or revoked_at,
            expires_at=expires_at or self.expires_at,
            last_used_at=last_used_at or self.last_used_at,
        )


@dataclass(frozen=True, slots=True)
class GatewayToken:
    id: str
    account_id: str
    prefix: str
    token_hash: str
    status: TokenStatus
    created_at: datetime
    grace_until: datetime | None = None
    """Set when the token was rotated: it keeps working until then."""
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None

    @property
    def rotated(self) -> bool:
        return self.grace_until is not None

    def valid(self, now: datetime) -> bool:
        return self.status == "active" and (self.grace_until is None or now < self.grace_until)

    def current_status(self, now: datetime) -> TokenStatus:
        """``revoked`` once a rotated token's grace period is over, even before the sweep writes it down."""
        if self.status == "active" and self.grace_until is not None and now >= self.grace_until:
            return "revoked"
        return self.status

    def rotate_out(self, now: datetime) -> GatewayToken:
        return replace(self, grace_until=now + ROTATION_GRACE, revoke_reason="rotated")

    def revoke(self, at: datetime, reason: str) -> GatewayToken:
        if self.status != "active":
            return self
        return replace(self, status="revoked", revoked_at=at, revoke_reason=reason)

    def expire(self, at: datetime) -> GatewayToken:
        if self.status != "active":
            return self
        return replace(self, status="expired", revoked_at=at, revoke_reason=self.revoke_reason or "expired")

    def settle(self, now: datetime) -> GatewayToken:
        """Write down the end of a grace period."""
        if self.current_status(now) == "revoked" and self.status == "active":
            return replace(self, status="revoked", revoked_at=self.grace_until)
        return self


def new_gateway_token() -> str:
    """``agn_pat_`` and 32 URL-safe random characters (192 bits)."""
    return GATEWAY_TOKEN_PREFIX + secrets.token_urlsafe(24)


def looks_like_gateway_token(value: str) -> bool:
    return value.startswith(GATEWAY_TOKEN_PREFIX) and len(value) > len(GATEWAY_TOKEN_PREFIX)


def display_prefix(token: str) -> str:
    return token[:DISPLAY_PREFIX_LENGTH]


def hash_token(pepper: str, token: str) -> str:
    return hashlib.sha256((pepper + token).encode()).hexdigest()


def isolation_note(account: ServiceAccount, scopes: tuple[str, ...] | list[str]) -> str:
    """How the runtime attributes the account's runs, in the words the detail panel shows."""
    if account.forwards_user_id:
        note = (
            f"Sends user_id per request, so user isolation applies to each of its users. Without one, runs are "
            f"owned by {account.subject} (gateway) or {account.principal} (native token)."
        )
    else:
        note = (
            f"No user_id: runs are owned by {account.principal} with its native token and by {account.subject} "
            "through the gateway; a user_id it sends is dropped."
        )
    if any(scope.split(":")[0] == "approvals" for scope in scopes):
        note += " Can post approvals but not resolve them: scoped service accounts get 404 on resolve."
    return note


def source_label(scope_source: ScopeSource, role_name: str | None, extra_count: int) -> str:
    if scope_source == "custom" or role_name is None:
        return "Custom scopes"
    if extra_count == 0:
        return f"Access role: {role_name}"
    return f"Access role: {role_name} + {extra_count} scope{'s' if extra_count != 1 else ''}"


def cli_command(
    name: str,
    *,
    instances: list[str] | tuple[str, ...],
    role: str | None,
    scopes: list[str] | tuple[str, ...],
    expires_in: str,
    kinds: list[str] | tuple[str, ...],
    forwards_user_id: bool = False,
    privileged: bool = False,
) -> str:
    """The ``agnostic tokens create`` command that does what the create form does."""
    lines = [f"agnostic tokens create {name or '<name>'}"]
    lines.extend(f"--instance {slug}" for slug in instances)
    if role:
        lines.append(f"--role {role}")
        if scopes:
            lines.append(f"--extra-scopes {','.join(scopes)}")
    elif scopes:
        lines.append(f"--scopes {','.join(scopes)}")
    lines.append(f"--expires-in {expires_in}")
    lines.extend(f"--kind {kind}" for kind in kinds)
    if forwards_user_id:
        lines.append("--forwards-user-id")
    if privileged or privileged_scopes(list(scopes)):
        lines.append("--yes-privileged")
    return " \\\n  ".join(lines)


def sample_agent(scopes: tuple[str, ...] | list[str]) -> str:
    """An agent the account may run, for the curl sample."""
    for scope in sorted(scopes):
        parts = scope.split(":")
        if len(parts) == 3 and parts[0] == "agents" and parts[2] == "run":  # noqa: PLR2004
            return parts[1]
    return "<agent-id>"


def curl_sample(base_url: str, *, variable: str, agent_id: str) -> str:
    return (
        f"curl -X POST {base_url.rstrip('/')}/agents/{agent_id}/runs \\\n"
        f'  -H "Authorization: Bearer ${variable}" \\\n'
        '  -F message="Hello from a service account"'
    )
