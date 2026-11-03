"""Step-up re-authentication: prove it's you again before a sensitive change.

A password, an authenticator code or a security key will do. People who only sign in through SSO step up by
signing in through their provider again (a fresh session).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.application.mfa import SecondFactors
from agnostic_identity.application.ports import (
    CredentialRepository,
    ExternalIdentityRepository,
    PasswordHasher,
    SignInClients,
    UserRepository,
)
from agnostic_identity.application.sessions import InteractiveSessionRequiredError, Sessions
from agnostic_identity.application.signin import AccountLockedError, SignInPolicy
from agnostic_identity.domain.mfa import MfaMethod
from agnostic_identity.domain.policy import REAUTH_WINDOW, is_recent
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import UnauthenticatedError, ValidationFailedError


@dataclass(frozen=True, slots=True)
class StepUpStatus:
    authenticated_at: datetime | None
    recent: bool
    expires_at: datetime | None
    methods: tuple[str, ...]
    """``password``, ``totp``, ``webauthn``; ``sso`` when the person can sign in again through ``sso_providers``."""
    sso_providers: tuple[str, ...]


class StepUpFailedError(ValidationFailedError):
    """422, not 401: a wrong answer in the step-up dialog doesn't end the session."""

    code = "step_up_failed"
    title = "That didn't confirm it's you"


def _session_key(principal: Principal) -> str:
    if principal.kind != "user" or principal.session_id is None:
        raise InteractiveSessionRequiredError("Sign in to the web app to confirm it's you.")
    return principal.session_id


class _StepUpBase:
    def __init__(
        self,
        sessions: Sessions,
        credentials: CredentialRepository,
        factors: SecondFactors,
        externals: ExternalIdentityRepository,
        clients: SignInClients,
    ) -> None:
        self._sessions = sessions
        self._credentials = credentials
        self._factors = factors
        self._externals = externals
        self._clients = clients

    async def _methods(self, user_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        methods: list[str] = []
        if await self._credentials.password_hash(user_id) is not None:
            methods.append("password")
        methods.extend(m.value for m in await self._factors.methods(user_id) if m is not MfaMethod.RECOVERY_CODE)
        enabled = {config.id for config in await self._clients.all()}
        providers = tuple(p for p in await self._externals.providers_of(user_id) if p in enabled)
        if providers:
            methods.append("sso")
        return tuple(methods), providers


class GetStepUp(_StepUpBase):
    async def __call__(self, principal: Principal) -> StepUpStatus:
        session = await self._sessions.load(_session_key(principal))
        authenticated_at = session.authenticated_at if session else None
        methods, providers = await self._methods(principal.id)
        return StepUpStatus(
            authenticated_at=authenticated_at,
            recent=is_recent(authenticated_at, utcnow()),
            expires_at=authenticated_at + REAUTH_WINDOW if authenticated_at else None,
            methods=methods,
            sso_providers=providers,
        )


class StepUpWebAuthnOptions(_StepUpBase):
    async def __call__(self, principal: Principal) -> dict[str, Any]:
        key = _session_key(principal)
        return await self._factors.authentication_options(principal.id, f"stepup:{key}")


class StepUp(_StepUpBase):
    def __init__(
        self,
        sessions: Sessions,
        credentials: CredentialRepository,
        factors: SecondFactors,
        externals: ExternalIdentityRepository,
        clients: SignInClients,
        users: UserRepository,
        hasher: PasswordHasher,
        store: EphemeralStore,
        audit: AuditLog,
        policy: SignInPolicy,
    ) -> None:
        super().__init__(sessions, credentials, factors, externals, clients)
        self._users = users
        self._hasher = hasher
        self._store = store
        self._audit = audit
        self._policy = policy

    async def __call__(
        self,
        principal: Principal,
        *,
        password: str | None = None,
        code: str | None = None,
        webauthn: Mapping[str, Any] | None = None,
    ) -> datetime:
        key = _session_key(principal)
        if not (password or code or webauthn):
            raise ValidationFailedError("Give your password, an authenticator code or a security key response.")
        fail_key = f"stepup:fail:{principal.id}"
        if int(await self._store.get(fail_key) or 0) >= self._policy.lockout_threshold:
            minutes = self._policy.lockout_seconds // 60
            raise AccountLockedError(f"Too many failed attempts. Try again in {minutes} minutes.")

        method: str | None = None
        if password:
            if await self._hasher.verify(await self._credentials.password_hash(principal.id), password):
                method = "password"
        elif code:
            if await self._factors.check_totp(principal.id, code):
                method = MfaMethod.TOTP.value
        elif webauthn and await self._factors.check_webauthn(principal.id, webauthn, f"stepup:{key}"):
            method = MfaMethod.WEBAUTHN.value

        actor = actor_of(principal)
        if method is None:
            _ = await self._store.incr(fail_key, ttl=self._policy.lockout_seconds)
            tried = "password" if password else "totp" if code else "webauthn"
            _ = await self._audit.record_now(
                AuditEntry(
                    action="auth.step_up_failed",
                    actor=actor,
                    resource_kind="user",
                    resource_id=principal.id,
                    resource_display=principal.email,
                    decision="denied",
                    fields={"method": tried},
                )
            )
            raise StepUpFailedError("That password isn't right." if password else "That didn't work. Try again.")

        at = await self._sessions.mark_authenticated(key)
        if at is None:
            raise UnauthenticatedError("Your session ended. Sign in again.")
        await self._store.delete(fail_key)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.step_up",
                actor=actor,
                resource_kind="user",
                resource_id=principal.id,
                resource_display=principal.email,
                fields={"method": method},
            )
        )
        await self._users.commit()
        return at
