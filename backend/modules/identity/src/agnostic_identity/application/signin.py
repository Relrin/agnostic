"""Signing in and out: email + password, and SSO through OIDC / OAuth 2 providers."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import orjson

from agnostic_audit.facade import Actor, AuditEntry, AuditLog
from agnostic_identity.application.ports import (
    CredentialRepository,
    ExternalIdentityRepository,
    MembershipDirectory,
    PasswordHasher,
    SignInClients,
    UserRepository,
)
from agnostic_identity.application.sessions import IssuedSession, Sessions
from agnostic_identity.domain.providers import SsoError
from agnostic_identity.domain.users import (
    CreatedVia,
    InvalidEmailError,
    User,
    clean_display_name,
    normalize_email,
    safe_next,
)
from agnostic_kernel.context import current_client
from agnostic_kernel.crypto import hash_token, new_token
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError, RateLimitedError, UnauthenticatedError

SSO_STATE_TTL = 600


@dataclass(frozen=True, slots=True)
class SignInPolicy:
    local_login: bool
    lockout_threshold: int
    lockout_seconds: int
    attempts_per_ip_per_minute: int
    password_min_length: int
    password_reset_seconds: int
    public_url: str

    def callback_url(self, provider_id: str) -> str:
        return f"{self.public_url}/api/v1/auth/sso/{provider_id}/callback"


class InvalidCredentialsError(UnauthenticatedError):
    code = "invalid_credentials"
    title = "Email or password is wrong"


class AccountLockedError(AppError):
    status = 429
    code = "account_locked"
    title = "Too many failed sign-ins"


class LocalLoginDisabledError(ForbiddenError):
    code = "local_login_disabled"
    title = "Password sign-in is turned off"


class NotAMemberError(ForbiddenError):
    code = "not_a_member"
    title = "This account isn't part of the org"


def _user_actor(user: User) -> Actor:
    return Actor(kind="user", id=user.id, display=user.display_name)


class Login:
    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        hasher: PasswordHasher,
        sessions: Sessions,
        directory: MembershipDirectory,
        audit: AuditLog,
        store: EphemeralStore,
        policy: SignInPolicy,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._sessions = sessions
        self._directory = directory
        self._audit = audit
        self._store = store
        self._policy = policy

    async def __call__(self, email: str, password: str) -> tuple[User, IssuedSession]:
        if not self._policy.local_login:
            raise LocalLoginDisabledError("Sign in with your organization's SSO provider.")
        ip = current_client().ip or "unknown"
        if await self._store.incr(f"rl:login:ip:{ip}", ttl=60) > self._policy.attempts_per_ip_per_minute:
            raise RateLimitedError("Too many sign-in attempts from this address. Wait a minute and try again.")
        try:
            normalized = normalize_email(email)
        except InvalidEmailError as exc:
            raise InvalidCredentialsError from exc

        lock_key = f"login:fail:{hash_token(normalized)}"
        failures = int(await self._store.get(lock_key) or 0)
        if failures >= self._policy.lockout_threshold:
            await self._failed(normalized, "locked")
            minutes = self._policy.lockout_seconds // 60
            raise AccountLockedError(f"Too many failed sign-ins. Try again in {minutes} minutes.")

        user = await self._users.find_by_email(normalized)
        password_hash = await self._credentials.password_hash(user.id) if user else None
        verified = await self._hasher.verify(password_hash, password)
        if user is None or not verified or not user.active:
            _ = await self._store.incr(lock_key, ttl=self._policy.lockout_seconds)
            await self._failed(normalized, "invalid_credentials" if user is None or not verified else "disabled")
            raise InvalidCredentialsError("Check your email and password and try again.")

        membership = await self._directory.membership(user.id)
        if membership is None or not membership.active:
            await self._failed(normalized, "not_a_member")
            raise NotAMemberError("Ask an Owner or Administrator for a new invitation.")

        await self._store.delete(lock_key)
        assert password_hash is not None
        if self._hasher.needs_rehash(password_hash):
            await self._credentials.set_password_hash(user.id, await self._hasher.hash(password))
        issued = await self._sessions.issue(user, method="password")
        now = utcnow()
        await self._credentials.mark_used(user.id, now)
        await self._users.touch(user.id, now)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.login",
                actor=_user_actor(user),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"method": "password"},
            )
        )
        await self._users.commit()
        return user, issued

    async def _failed(self, email: str, reason: str) -> None:
        _ = await self._audit.record_now(
            AuditEntry(
                action="auth.login_failed",
                actor=Actor(kind="anonymous", id=email, display=email),
                resource_kind="user",
                resource_display=email,
                decision="denied",
                fields={"email": email, "reason": reason},
            )
        )


class Logout:
    def __init__(self, sessions: Sessions, users: UserRepository, audit: AuditLog) -> None:
        self._sessions = sessions
        self._users = users
        self._audit = audit

    async def __call__(self, actor: Actor, session_key: str) -> None:
        await self._sessions.revoke(session_key)
        _ = await self._audit.record(AuditEntry(action="auth.logout", actor=actor))
        await self._users.commit()


@dataclass(frozen=True, slots=True)
class _SsoState:
    provider_id: str
    nonce: str
    verifier: str
    next: str


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class StartSso:
    def __init__(self, clients: SignInClients, store: EphemeralStore, policy: SignInPolicy) -> None:
        self._clients = clients
        self._store = store
        self._policy = policy

    async def __call__(self, provider_id: str, next_path: str | None) -> str:
        client = self._clients.get(provider_id)
        if client is None:
            raise NotFoundError(f"There is no sign-in provider {provider_id!r}.")
        state, nonce, verifier = new_token(24), new_token(24), new_token(48)
        payload = {"provider_id": provider_id, "nonce": nonce, "verifier": verifier, "next": safe_next(next_path)}
        await self._store.set(f"sso:{state}", orjson.dumps(payload), ttl=SSO_STATE_TTL)
        return await client.authorization_url(
            redirect_uri=self._policy.callback_url(provider_id),
            state=state,
            nonce=nonce,
            code_challenge=_challenge(verifier),
        )


class CompleteSso:
    def __init__(
        self,
        clients: SignInClients,
        users: UserRepository,
        externals: ExternalIdentityRepository,
        sessions: Sessions,
        directory: MembershipDirectory,
        audit: AuditLog,
        store: EphemeralStore,
        policy: SignInPolicy,
    ) -> None:
        self._clients = clients
        self._users = users
        self._externals = externals
        self._sessions = sessions
        self._directory = directory
        self._audit = audit
        self._store = store
        self._policy = policy

    async def __call__(self, provider_id: str, code: str, state: str) -> tuple[User, IssuedSession, str]:  # noqa: C901
        raw = await self._store.pop(f"sso:{state}")
        if raw is None:
            raise SsoError("state_expired", "The sign-in took too long or was already used. Start again.")
        saved = _SsoState(**orjson.loads(raw))
        client = self._clients.get(provider_id)
        if client is None or saved.provider_id != provider_id:
            raise SsoError("state_mismatch", "The sign-in response doesn't belong to this provider.")

        profile = await client.complete(
            redirect_uri=self._policy.callback_url(provider_id),
            code=code,
            code_verifier=saved.verifier,
            nonce=saved.nonce,
        )
        if not profile.email:
            raise SsoError("email_missing", f"{client.config.display_name} didn't share an email address.")
        if not profile.email_verified and not client.config.trust_unverified_email:
            raise SsoError("email_unverified", f"Verify your email address at {client.config.display_name} first.")
        try:
            email = normalize_email(profile.email)
        except InvalidEmailError as exc:
            raise SsoError("email_missing", str(exc)) from exc

        linked_id = await self._externals.find_user(provider_id, profile.subject)
        user = await self._users.get(linked_id) if linked_id else await self._users.find_by_email(email)
        if user is not None and not user.active:
            await self._failed(email, provider_id, "account_disabled")
            raise SsoError("account_disabled", "Your account is disabled. Ask an Owner or Administrator.")

        membership = await self._directory.membership(user.id) if user else None
        if membership is None or not membership.active:
            admission = await self._directory.admit(email, jit_allowed=client.config.jit_allows(email))
            if not admission.allowed:
                reason = admission.reason or "not_invited"
                await self._failed(email, provider_id, reason)
                raise SsoError(reason, "You need an invitation to join this org.")
            if user is None:
                user = await self._users.add(
                    email=email,
                    display_name=clean_display_name(profile.display_name, email),
                    created_via=CreatedVia.OIDC,
                )
            await self._directory.join(user, via=f"sso:{provider_id}")
        assert user is not None
        if linked_id is None:
            await self._externals.link(user.id, provider_id, profile)

        issued = await self._sessions.issue(user, method=f"sso:{provider_id}")
        await self._users.touch(user.id, utcnow())
        _ = await self._audit.record(
            AuditEntry(
                action="auth.login",
                actor=_user_actor(user),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"method": client.config.display_name},
            )
        )
        await self._users.commit()
        return user, issued, saved.next

    async def _failed(self, email: str, provider_id: str, reason: str) -> None:
        _ = await self._audit.record_now(
            AuditEntry(
                action="auth.login_failed",
                actor=Actor(kind="anonymous", id=email, display=email),
                resource_kind="user",
                resource_display=email,
                decision="denied",
                fields={"email": email, "reason": f"{reason} via {provider_id}"},
            )
        )
