"""Second factors: enrollment (``/me/mfa``), checking them at sign-in and step-up, recovery codes."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import orjson

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import MembershipDirectory, MfaRepository, UserRepository, WebAuthnVerifier
from agnostic_identity.application.sessions import RecentAuth
from agnostic_identity.domain import totp
from agnostic_identity.domain.mfa import (
    Factor,
    MfaMethod,
    clean_label,
    methods_for,
    new_recovery_codes,
    normalize_recovery_code,
)
from agnostic_identity.domain.policy import MfaPolicy
from agnostic_identity.domain.users import User
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import SecretBox, SecretDecryptionError, hash_token, new_token
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationFailedError

ISSUER = "Agnostic"
PENDING_TOTP_SECONDS = 600
WEBAUTHN_CHALLENGE_SECONDS = 300
LOGIN_CHALLENGE_SECONDS = 300
MAX_CHALLENGE_ATTEMPTS = 5
_USED_STEP_SECONDS = (totp.WINDOW * 2 + 2) * totp.STEP_SECONDS


class MfaDisabledError(ForbiddenError):
    code = "mfa_disabled"
    title = "Two-step verification is turned off for this org"


class MfaInvalidError(AppError):
    status = 401
    code = "mfa_invalid"
    title = "That code didn't work"


class MfaChallengeExpiredError(AppError):
    status = 401
    code = "mfa_challenge_expired"
    title = "The sign-in took too long"


def recovery_hash(code: str) -> str:
    return hash_token(f"recovery:{normalize_recovery_code(code)}")


class SecondFactors:
    """Checks and enrolls factors. ``purpose`` keys a WebAuthn challenge to one ceremony (``me:…``, ``login:…``)."""

    def __init__(self, mfa: MfaRepository, store: EphemeralStore, webauthn: WebAuthnVerifier, box: SecretBox) -> None:
        self._mfa = mfa
        self._store = store
        self._webauthn = webauthn
        self._box = box

    async def methods(self, user_id: str) -> tuple[MfaMethod, ...]:
        factors = await self._mfa.factors(user_id)
        return methods_for(factors, has_recovery_codes=await self._mfa.recovery_codes_left(user_id) > 0)

    async def has_factor(self, user_id: str) -> bool:
        return bool(await self._mfa.factors(user_id))

    # ------------------------------------------------------------------ checking
    async def check_totp(self, user_id: str, code: str) -> str | None:
        """The authenticator-app factor id when ``code`` is right and wasn't used before."""
        stored = await self._mfa.totp_secret(user_id)
        if stored is None:
            return None
        factor_id, secret = stored
        step = totp.verify(totp.decode_secret(secret), code, time.time())
        if step is None:
            return None
        if not await self._store.set_if_absent(f"mfa:totp:used:{user_id}:{step}", b"1", ttl=_USED_STEP_SECONDS):
            return None  # the same code twice (a replayed or shoulder-surfed code)
        await self._mfa.mark_used(factor_id, utcnow())
        return factor_id

    async def check_recovery_code(self, user_id: str, code: str) -> bool:
        return await self._mfa.use_recovery_code(user_id, recovery_hash(code), utcnow())

    async def authentication_options(self, user_id: str, purpose: str) -> dict[str, Any]:
        credentials = await self._mfa.webauthn_credentials(user_id)
        if not credentials:
            raise NotFoundError("You have no security keys or passkeys.")
        options, challenge = self._webauthn.authentication_options(credentials)
        await self._store.set(f"mfa:webauthn:{purpose}", challenge, ttl=WEBAUTHN_CHALLENGE_SECONDS)
        return options

    async def check_webauthn(self, user_id: str, credential: Mapping[str, Any], purpose: str) -> str | None:
        challenge = await self._store.pop(f"mfa:webauthn:{purpose}")
        raw_id = self._webauthn.credential_id(credential)
        if challenge is None or raw_id is None:
            return None
        stored = next(
            (item for item in await self._mfa.webauthn_credentials(user_id) if item.credential_id == raw_id), None
        )
        if stored is None:
            return None
        try:
            sign_count = self._webauthn.verify_authentication(credential, challenge, stored)
        except ValueError:
            return None
        await self._mfa.update_sign_count(stored.factor_id, sign_count, utcnow())
        return stored.factor_id

    async def verify(
        self,
        user_id: str,
        *,
        code: str | None,
        recovery_code: str | None,
        webauthn: Mapping[str, Any] | None,
        purpose: str,
    ) -> MfaMethod | None:
        """Whichever answer was given; the method that accepted it, or ``None``."""
        if code and await self.check_totp(user_id, code):
            return MfaMethod.TOTP
        if webauthn and await self.check_webauthn(user_id, webauthn, purpose):
            return MfaMethod.WEBAUTHN
        if recovery_code and await self.check_recovery_code(user_id, recovery_code):
            return MfaMethod.RECOVERY_CODE
        return None

    # ------------------------------------------------------------------ enrollment
    async def start_totp(self, user: User) -> tuple[str, str]:
        """A new secret, pending until a code from it is confirmed."""
        secret = totp.new_secret()
        sealed = self._box.seal(secret.encode())
        await self._store.set(f"mfa:totp:pending:{user.id}", sealed.encode(), ttl=PENDING_TOTP_SECONDS)
        return secret, totp.otpauth_uri(secret, account=user.email, issuer=ISSUER)

    async def confirm_totp(self, user: User, code: str, *, label: str | None) -> Factor | None:
        """``None`` when the code is wrong; raises when there is no pending setup."""
        raw = await self._store.get(f"mfa:totp:pending:{user.id}")
        if raw is None:
            raise ValidationFailedError("Start the authenticator app setup again (it expired after 10 minutes).")
        try:
            secret = self._box.open(raw.decode()).decode()
        except SecretDecryptionError as exc:
            raise ValidationFailedError("Start the authenticator app setup again.") from exc
        step = totp.verify(totp.decode_secret(secret), code, time.time())
        if step is None:
            return None
        await self._store.delete(f"mfa:totp:pending:{user.id}")
        _ = await self._store.set_if_absent(f"mfa:totp:used:{user.id}:{step}", b"1", ttl=_USED_STEP_SECONDS)
        return await self._mfa.set_totp(user.id, secret, label=clean_label(label, "Authenticator app"))

    async def registration_options(self, user: User, purpose: str) -> dict[str, Any]:
        existing = [item.credential_id for item in await self._mfa.webauthn_credentials(user.id)]
        options, challenge = self._webauthn.registration_options(
            user_id=user.id, user_name=user.email, display_name=user.display_name, exclude=existing
        )
        await self._store.set(f"mfa:webauthn:{purpose}", challenge, ttl=WEBAUTHN_CHALLENGE_SECONDS)
        return options

    async def register_webauthn(
        self, user: User, credential: Mapping[str, Any], *, label: str | None, purpose: str
    ) -> Factor | None:
        """``None`` when the response doesn't verify."""
        challenge = await self._store.pop(f"mfa:webauthn:{purpose}")
        if challenge is None:
            return None
        try:
            created = self._webauthn.verify_registration(credential, challenge)
        except ValueError:
            return None
        existing = {item.credential_id for item in await self._mfa.webauthn_credentials(user.id)}
        if created.credential_id in existing:
            raise ConflictError("This security key is already registered.")
        return await self._mfa.add_webauthn(user.id, created, label=clean_label(label, "Security key"))

    async def issue_recovery_codes(self, user_id: str) -> list[str]:
        codes = new_recovery_codes()
        await self._mfa.replace_recovery_codes(user_id, [recovery_hash(code) for code in codes])
        return codes


@dataclass(frozen=True, slots=True)
class MfaStatus:
    policy: MfaPolicy
    required: bool
    """The policy requires a second factor for this person."""
    factors: list[Factor]
    recovery_codes_left: int


@dataclass(frozen=True, slots=True)
class Enrolled:
    factor: Factor
    recovery_codes: list[str]
    """New recovery codes when this was the first factor (shown once); otherwise empty."""


class _MfaUseCase:
    def __init__(
        self,
        users: UserRepository,
        mfa: MfaRepository,
        factors: SecondFactors,
        policies: AuthPolicies,
        directory: MembershipDirectory,
        recent: RecentAuth,
        audit: AuditLog,
    ) -> None:
        self._users = users
        self._mfa = mfa
        self._factors = factors
        self._policies = policies
        self._directory = directory
        self._recent = recent
        self._audit = audit

    async def _user(self, principal: Principal) -> User:
        user = await self._users.get(principal.id) if principal.kind == "user" else None
        if user is None:
            raise NotFoundError("Your account doesn't exist any more.")
        return user

    async def _enrollable(self, principal: Principal) -> User:
        if not (await self._policies.current()).enrollment_allowed:
            raise MfaDisabledError("Your org turned two-step verification off.")
        return await self._user(principal)

    async def _enrolled(self, user: User, principal: Principal, factor: Factor) -> Enrolled:
        first = await self._mfa.recovery_codes_left(user.id) == 0
        codes = await self._factors.issue_recovery_codes(user.id) if first else []
        _ = await self._audit.record(
            AuditEntry(
                action="auth.mfa.enroll",
                actor=actor_of(principal),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"factor": factor.kind.value, "label": factor.label},
            )
        )
        await self._users.commit()
        return Enrolled(factor=factor, recovery_codes=codes)


class GetMyMfa(_MfaUseCase):
    async def __call__(self, principal: Principal) -> MfaStatus:
        user = await self._user(principal)
        policy = await self._policies.current()
        membership = await self._directory.membership(user.id)
        return MfaStatus(
            policy=policy.mfa_policy,
            required=policy.mfa_required_for(membership.org_role if membership else None),
            factors=await self._mfa.factors(user.id),
            recovery_codes_left=await self._mfa.recovery_codes_left(user.id),
        )


class SetupTotp(_MfaUseCase):
    async def __call__(self, principal: Principal) -> tuple[str, str]:
        return await self._factors.start_totp(await self._enrollable(principal))


class ConfirmTotp(_MfaUseCase):
    async def __call__(self, principal: Principal, code: str, label: str | None) -> Enrolled:
        user = await self._enrollable(principal)
        factor = await self._factors.confirm_totp(user, code, label=label)
        if factor is None:
            raise ValidationFailedError("That code didn't match. Check the time on your device and try again.")
        return await self._enrolled(user, principal, factor)


class WebAuthnRegistrationOptions(_MfaUseCase):
    async def __call__(self, principal: Principal) -> dict[str, Any]:
        user = await self._enrollable(principal)
        return await self._factors.registration_options(user, f"me:{user.id}")


class VerifyWebAuthnRegistration(_MfaUseCase):
    async def __call__(self, principal: Principal, credential: Mapping[str, Any], label: str | None) -> Enrolled:
        user = await self._enrollable(principal)
        factor = await self._factors.register_webauthn(user, credential, label=label, purpose=f"me:{user.id}")
        if factor is None:
            raise ValidationFailedError("The security key's response didn't verify. Try again.")
        return await self._enrolled(user, principal, factor)


class RemoveFactor(_MfaUseCase):
    async def __call__(self, principal: Principal, factor_id: str) -> None:
        user = await self._user(principal)
        await self._recent.require(principal)
        factors = await self._mfa.factors(user.id)
        if not any(factor.id == factor_id for factor in factors):
            raise NotFoundError("That factor doesn't exist.")
        if len(factors) == 1:
            membership = await self._directory.membership(user.id)
            policy = await self._policies.current()
            if policy.mfa_required_for(membership.org_role if membership else None):
                raise ConflictError("Your org requires two-step verification; add another factor first.")
        removed = await self._mfa.remove(user.id, factor_id)
        assert removed is not None
        if len(factors) == 1:
            await self._mfa.remove_all(user.id)  # recovery codes go with the last factor
        _ = await self._audit.record(
            AuditEntry(
                action="auth.mfa.remove",
                actor=actor_of(principal),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"factor": removed.kind.value, "label": removed.label},
            )
        )
        await self._users.commit()


class RegenerateRecoveryCodes(_MfaUseCase):
    async def __call__(self, principal: Principal) -> list[str]:
        user = await self._user(principal)
        await self._recent.require(principal)
        if not await self._factors.has_factor(user.id):
            raise ConflictError("Add an authenticator app or a security key first.")
        codes = await self._factors.issue_recovery_codes(user.id)
        _ = await self._audit.record(
            AuditEntry(
                action="auth.mfa.recovery_codes",
                actor=actor_of(principal),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
            )
        )
        await self._users.commit()
        return codes


@dataclass(frozen=True, slots=True)
class LoginChallenge:
    user_id: str
    email: str
    enroll: bool
    attempts: int = 0


class LoginChallenges:
    """The step between a correct password and a session: a short-lived, single-use token."""

    def __init__(self, store: EphemeralStore) -> None:
        self._store = store

    @staticmethod
    def purpose(token: str) -> str:
        return f"login:{hash_token(token)}"

    async def open(self, user: User, *, enroll: bool) -> str:
        token = new_token(32)
        payload = {"user_id": user.id, "email": user.email, "enroll": enroll, "attempts": 0}
        await self._store.set(f"mfa:{self.purpose(token)}", orjson.dumps(payload), ttl=LOGIN_CHALLENGE_SECONDS)
        return token

    async def get(self, token: str) -> LoginChallenge | None:
        raw = await self._store.get(f"mfa:{self.purpose(token)}")
        return LoginChallenge(**orjson.loads(raw)) if raw else None

    async def failed(self, token: str, challenge: LoginChallenge) -> int:
        """Count a wrong answer; after five the challenge is gone and the person signs in again."""
        attempts = challenge.attempts + 1
        key = f"mfa:{self.purpose(token)}"
        if attempts >= MAX_CHALLENGE_ATTEMPTS:
            await self._store.delete(key)
        else:
            payload = {"user_id": challenge.user_id, "email": challenge.email, "enroll": challenge.enroll}
            await self._store.set(key, orjson.dumps({**payload, "attempts": attempts}), ttl=LOGIN_CHALLENGE_SECONDS)
        return attempts

    async def close(self, token: str) -> None:
        await self._store.delete(f"mfa:{self.purpose(token)}", f"mfa:webauthn:{self.purpose(token)}")
