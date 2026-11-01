"""Ports of the identity module.

:class:`MembershipDirectory` is implemented by the ``org`` module: identity knows accounts, org knows who belongs
to the org (and with which role). Identity asks it whether an account may sign in and whether a newcomer from an
SSO provider may join.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agnostic_identity.domain.providers import ExternalProfile, ProviderConfig
from agnostic_identity.domain.users import CreatedVia, User, UserStatus, WebSession


class UserRepository(Protocol):
    async def add(self, *, email: str, display_name: str, created_via: CreatedVia) -> User: ...
    async def get(self, user_id: str) -> User | None: ...
    async def get_many(self, user_ids: Sequence[str]) -> list[User]: ...
    async def find_by_email(self, email: str) -> User | None: ...
    async def update(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        status: UserStatus | None = None,
    ) -> User: ...
    async def touch(self, user_id: str, at: datetime) -> None: ...
    async def commit(self) -> None: ...


class CredentialRepository(Protocol):
    async def password_hash(self, user_id: str) -> str | None: ...
    async def set_password_hash(self, user_id: str, password_hash: str) -> None: ...
    async def mark_used(self, user_id: str, at: datetime) -> None: ...


class ExternalIdentityRepository(Protocol):
    async def find_user(self, provider_id: str, subject: str) -> str | None: ...
    async def link(self, user_id: str, provider_id: str, profile: ExternalProfile) -> None: ...
    async def providers_of(self, user_id: str) -> list[str]: ...


class PreferenceRepository(Protocol):
    async def all(self, user_id: str) -> dict[str, Any]: ...
    async def set_many(self, user_id: str, values: Mapping[str, Any]) -> None: ...


class SessionRecordRepository(Protocol):
    """The audit copy of web sessions (live state is in the ephemeral store)."""

    async def add(self, session: WebSession) -> None: ...
    async def active_keys(self, user_id: str) -> list[str]: ...
    async def list_active(self, user_id: str) -> list[WebSession]: ...
    async def revoke(self, keys: Sequence[str], at: datetime) -> None: ...


class SessionStore(Protocol):
    async def save(self, session: WebSession, ttl: float) -> None: ...
    async def load(self, key: str) -> WebSession | None: ...
    async def delete(self, *keys: str) -> None: ...


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...
    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Constant-ish time: also burns a verification when there is no hash."""
        ...

    def needs_rehash(self, password_hash: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    url: str
    state: str


class SignInClient(Protocol):
    """One configured SSO provider."""

    config: ProviderConfig

    async def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str: ...
    async def complete(self, *, redirect_uri: str, code: str, code_verifier: str, nonce: str) -> ExternalProfile: ...


class SignInClients(Protocol):
    def get(self, provider_id: str) -> SignInClient | None: ...
    def all(self) -> list[ProviderConfig]: ...


@dataclass(frozen=True, slots=True)
class Membership:
    org_role: str
    active: bool


@dataclass(frozen=True, slots=True)
class Admission:
    allowed: bool
    reason: str | None = None
    """``not_invited``, ``domain_not_allowed``, ``seats_full``: shown on the login page."""


class MembershipDirectory(Protocol):
    async def membership(self, user_id: str) -> Membership | None: ...
    async def admit(self, email: str, *, jit_allowed: bool) -> Admission:
        """May a person with this (verified) email join the org: a pending invitation, or JIT provisioning."""
        ...

    async def join(self, user: User, *, via: str) -> None:
        """Make ``user`` a member: accept their pending invitation (role, bindings) or join as Member (JIT)."""
        ...
