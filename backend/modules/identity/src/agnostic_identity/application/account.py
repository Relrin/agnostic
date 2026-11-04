"""The signed-in person's account: profile, preferences, password, sessions; and local account creation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import orjson

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import (
    CredentialRepository,
    ExternalIdentityRepository,
    MembershipDirectory,
    PasswordHasher,
    PreferenceRepository,
    SessionRecordRepository,
    UserRepository,
)
from agnostic_identity.application.sessions import Sessions
from agnostic_identity.application.signin import LocalLoginDisabledError, SignInPolicy, SsoRequiredError
from agnostic_identity.domain.users import (
    MAX_DISPLAY_NAME,
    CreatedVia,
    InvalidEmailError,
    User,
    UserStatus,
    WeakPasswordError,
    WebSession,
    check_password,
    clean_display_name,
    normalize_email,
)
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import hash_token, new_token
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.logging import get_logger
from agnostic_kernel.mail import Email, Mailer

log = get_logger(__name__)

_PREFERENCE_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
MAX_PREFERENCE_BYTES = 4096


@dataclass(frozen=True, slots=True)
class MeView:
    user: User
    org_role: str | None
    preferences: dict[str, Any]
    has_password: bool
    sso_providers: list[str]
    session_method: str | None


class GetMe:
    def __init__(
        self,
        users: UserRepository,
        preferences: PreferenceRepository,
        credentials: CredentialRepository,
        externals: ExternalIdentityRepository,
        directory: MembershipDirectory,
    ) -> None:
        self._users = users
        self._preferences = preferences
        self._credentials = credentials
        self._externals = externals
        self._directory = directory

    async def __call__(self, principal: Principal, session_method: str | None = None) -> MeView:
        user = await self._users.get(principal.id)
        if user is None:
            raise NotFoundError("Your account doesn't exist any more.")
        membership = await self._directory.membership(user.id)
        return MeView(
            user=user,
            org_role=membership.org_role if membership and membership.active else None,
            preferences=await self._preferences.all(user.id),
            has_password=await self._credentials.password_hash(user.id) is not None,
            sso_providers=await self._externals.providers_of(user.id),
            session_method=session_method,
        )


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    display_name: str | None = None
    locale: str | None = None
    timezone: str | None = None
    preferences: Mapping[str, Any] | None = None


def validate_preferences(values: Mapping[str, Any]) -> dict[str, Any]:
    for key in values:
        if not _PREFERENCE_KEY.fullmatch(key):
            raise ValidationFailedError(f"{key!r} is not a valid preference name.")
    if len(orjson.dumps(dict(values))) > MAX_PREFERENCE_BYTES:
        raise ValidationFailedError("Preferences are limited to 4 KB.")
    return dict(values)


class UpdateMe:
    def __init__(
        self,
        users: UserRepository,
        preferences: PreferenceRepository,
        sessions: Sessions,
        get_me: GetMe,
    ) -> None:
        self._users = users
        self._preferences = preferences
        self._sessions = sessions
        self._get_me = get_me

    async def __call__(self, principal: Principal, changes: ProfileChanges, session: WebSession | None) -> MeView:
        display_name = None
        if changes.display_name is not None:
            display_name = " ".join(changes.display_name.split())[:MAX_DISPLAY_NAME]
            if not display_name:
                raise ValidationFailedError("Your name can't be empty.")
        user = await self._users.update(
            principal.id, display_name=display_name, locale=changes.locale, timezone=changes.timezone
        )
        if changes.preferences is not None:
            await self._preferences.set_many(user.id, validate_preferences(changes.preferences))
        await self._users.commit()
        if session is not None and display_name is not None:
            await self._sessions.update_profile(session, display_name=display_name)
        return await self._get_me(principal, session.method if session else None)


class CreateLocalAccount:
    """Used by the org module for the first Owner and for invitation acceptance. The caller commits.

    Accepting an invitation with a password follows the sign-in rules: an invite link can be forwarded, so it
    doesn't prove who holds it, and where passwords are off or SSO is enforced the invitee joins through SSO.
    """

    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        hasher: PasswordHasher,
        policy: SignInPolicy,
        policies: AuthPolicies,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._policy = policy
        self._policies = policies

    async def __call__(self, email: str, display_name: str | None, password: str, via: CreatedVia) -> User:
        try:
            normalized = normalize_email(email)
        except InvalidEmailError as exc:
            raise ValidationFailedError(str(exc)) from exc
        try:
            check_password(password, email=normalized, min_length=self._policy.password_min_length)
        except WeakPasswordError as exc:
            raise ValidationFailedError(str(exc), extra={"field": "password"}) from exc
        existing = await self._users.find_by_email(normalized)
        if via is CreatedVia.INVITE:
            await self._check_password_allowed(existing)
        if existing is not None:
            if await self._credentials.password_hash(existing.id) is not None:
                raise ConflictError(f"An account for {normalized} already exists. Sign in instead.")
            user = existing
            if user.status is not UserStatus.ACTIVE:
                user = await self._users.update(user.id, status=UserStatus.ACTIVE)
        else:
            user = await self._users.add(
                email=normalized, display_name=clean_display_name(display_name, normalized), created_via=via
            )
        await self._credentials.set_password_hash(user.id, await self._hasher.hash(password))
        return user

    async def _check_password_allowed(self, existing: User | None) -> None:
        if not self._policy.local_login:
            raise LocalLoginDisabledError("Passwords are turned off: accept the invitation by signing in with SSO.")
        policy = await self._policies.current()
        allowed = policy.password_allowed(existing.id) if existing is not None else not policy.enforce_sso
        if not allowed:
            raise SsoRequiredError("Your organization uses SSO: accept the invitation by signing in with SSO.")


class RequestPasswordReset:
    def __init__(
        self,
        users: UserRepository,
        store: EphemeralStore,
        mailer: Mailer,
        audit: AuditLog,
        policy: SignInPolicy,
    ) -> None:
        self._users = users
        self._store = store
        self._mailer = mailer
        self._audit = audit
        self._policy = policy

    async def __call__(self, email: str) -> None:
        """Always succeeds from the caller's point of view, so it can't be used to discover accounts."""
        if not self._policy.local_login:
            raise LocalLoginDisabledError("Passwords are managed by your SSO provider.")
        try:
            normalized = normalize_email(email)
        except InvalidEmailError:
            return
        user = await self._users.find_by_email(normalized)
        if user is None or not user.active:
            log.info("identity.password_reset_unknown")
            return
        token = new_token(32)
        await self._store.set(f"pwreset:{hash_token(token)}", user.id.encode(), ttl=self._policy.password_reset_seconds)
        minutes = self._policy.password_reset_seconds // 60
        await self._mailer.send(
            Email(
                to=user.email,
                subject="Reset your Agnostic password",
                text=(
                    f"Hi {user.display_name},\n\nSomeone (hopefully you) asked to reset your password. "
                    f"Open this link within {minutes} minutes to choose a new one:\n\n"
                    f"{self._policy.public_url}/reset-password?token={token}\n\n"
                    "If it wasn't you, ignore this email; your password stays the same."
                ),
            )
        )
        _ = await self._audit.record_now(
            AuditEntry(
                action="auth.password_reset_requested",
                actor=actor_of(None),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
            )
        )


class ConfirmPasswordReset:
    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        hasher: PasswordHasher,
        sessions: Sessions,
        store: EphemeralStore,
        audit: AuditLog,
        policy: SignInPolicy,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._sessions = sessions
        self._store = store
        self._audit = audit
        self._policy = policy

    async def __call__(self, token: str, password: str) -> None:
        key = f"pwreset:{hash_token(token)}"
        user_id = await self._store.get(key)
        user = await self._users.get(user_id.decode()) if user_id else None
        if user is None:
            raise ValidationFailedError("This reset link expired or was already used. Ask for a new one.")
        try:
            check_password(password, email=user.email, min_length=self._policy.password_min_length)
        except WeakPasswordError as exc:
            raise ValidationFailedError(str(exc), extra={"field": "password"}) from exc
        await self._store.delete(key)
        await self._credentials.set_password_hash(user.id, await self._hasher.hash(password))
        await self._sessions.revoke_user(user.id)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.password_reset",
                actor=actor_of(Principal(kind="user", id=user.id, display_name=user.display_name)),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
            )
        )
        await self._users.commit()


class ListMySessions:
    def __init__(self, records: SessionRecordRepository) -> None:
        self._records = records

    async def __call__(self, principal: Principal) -> list[WebSession]:
        return await self._records.list_active(principal.id)


class RevokeMySession:
    def __init__(self, records: SessionRecordRepository, sessions: Sessions, users: UserRepository) -> None:
        self._records = records
        self._sessions = sessions
        self._users = users

    async def __call__(self, principal: Principal, session_key: str) -> None:
        if session_key not in await self._records.active_keys(principal.id):
            raise NotFoundError("That session doesn't exist or already ended.")
        await self._sessions.revoke(session_key)
        await self._users.commit()
