"""Signing in and out: email + password (with a second factor), and SSO through OIDC / OAuth 2 / SAML providers."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import orjson

from agnostic_audit.facade import Actor, AuditEntry, AuditLog
from agnostic_identity.application.mfa import LoginChallenges, MfaChallengeExpiredError, MfaInvalidError, SecondFactors
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import (
    CredentialRepository,
    ExternalGroupsSync,
    ExternalIdentityRepository,
    MembershipDirectory,
    PasswordHasher,
    SamlServiceProvider,
    SignInClients,
    SpEndpoints,
    UserRepository,
)
from agnostic_identity.application.sessions import IssuedSession, Sessions
from agnostic_identity.domain.mfa import Factor, FactorKind, MfaMethod
from agnostic_identity.domain.providers import ExternalProfile, ProviderConfig, SignInProtocol, SsoError, saml_profile
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
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError, RateLimitedError, UnauthenticatedError

SSO_STATE_TTL = 600
SAML_REPLAY_SKEW_SECONDS = 300
BREAK_GLASS_EVENT = "identity.break_glass_used"


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

    def service_provider(self, provider_id: str) -> SpEndpoints:
        """SAML: the entity id is the public SP metadata URL (IdPs can import it from there)."""
        base = f"{self.public_url}/api/v1/auth/sso/{provider_id}"
        return SpEndpoints(entity_id=f"{base}/metadata", acs_url=f"{base}/acs")


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


class SsoRequiredError(ForbiddenError):
    code = "sso_required"
    title = "Sign in with your organization's SSO provider"


class NotAMemberError(ForbiddenError):
    code = "not_a_member"
    title = "This account isn't part of the org"


def _user_actor(user: User) -> Actor:
    return Actor(kind="user", id=user.id, display=user.display_name)


def lock_key(email: str) -> str:
    return f"login:fail:{hash_token(email)}"


@dataclass(frozen=True, slots=True)
class MfaPending:
    """The password was right; a second factor (or enrolling one) comes before the session."""

    challenge: str
    methods: tuple[str, ...]
    enroll: bool


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    user: User
    issued: IssuedSession | None = None
    mfa: MfaPending | None = None
    recovery_codes: list[str] = field(default_factory=list[str])
    """Shown once, when a factor was enrolled as part of signing in."""


async def _failed_login(audit: AuditLog, email: str, reason: str) -> None:
    _ = await audit.record_now(
        AuditEntry(
            action="auth.login_failed",
            actor=Actor(kind="anonymous", id=email, display=email),
            resource_kind="user",
            resource_display=email,
            decision="denied",
            fields={"email": email, "reason": reason},
        )
    )


class FinishPasswordSignIn:
    """The password (and any second factor) checked out: issue the session, audit, flag break-glass use."""

    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        sessions: Sessions,
        audit: AuditLog,
        store: EphemeralStore,
        policies: AuthPolicies,
        events: DomainEvents,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._sessions = sessions
        self._audit = audit
        self._store = store
        self._policies = policies
        self._events = events

    async def __call__(self, user: User, *, factor: MfaMethod | None) -> IssuedSession:
        await self._store.delete(lock_key(user.email))
        issued = await self._sessions.issue(user, method="password")
        now = utcnow()
        await self._credentials.mark_used(user.id, now)
        await self._users.touch(user.id, now)
        method = "password" if factor is None else f"password + {factor.value.replace('_', ' ')}"
        _ = await self._audit.record(
            AuditEntry(
                action="auth.login",
                actor=_user_actor(user),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"method": method},
            )
        )
        policy = await self._policies.current()
        break_glass = policy.enforce_sso and policy.is_break_glass(user.id)
        ip = current_client().ip
        if break_glass:
            _ = await self._audit.record(
                AuditEntry(
                    action="auth.break_glass",
                    actor=_user_actor(user),
                    resource_kind="user",
                    resource_id=user.id,
                    resource_display=user.email,
                    fields={"ip": ip or "unknown"},
                )
            )
        await self._users.commit()
        if break_glass:
            await self._events.publish(
                BREAK_GLASS_EVENT, {"user_id": user.id, "user_name": user.display_name, "ip": ip}
            )
        return issued


class Login:
    def __init__(
        self,
        users: UserRepository,
        credentials: CredentialRepository,
        hasher: PasswordHasher,
        directory: MembershipDirectory,
        audit: AuditLog,
        store: EphemeralStore,
        policy: SignInPolicy,
        policies: AuthPolicies,
        factors: SecondFactors,
        challenges: LoginChallenges,
        finish: FinishPasswordSignIn,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._directory = directory
        self._audit = audit
        self._store = store
        self._policy = policy
        self._policies = policies
        self._factors = factors
        self._challenges = challenges
        self._finish = finish

    async def __call__(self, email: str, password: str) -> LoginOutcome:
        if not self._policy.local_login:
            raise LocalLoginDisabledError("Sign in with your organization's SSO provider.")
        ip = current_client().ip or "unknown"
        if await self._store.incr(f"rl:login:ip:{ip}", ttl=60) > self._policy.attempts_per_ip_per_minute:
            raise RateLimitedError("Too many sign-in attempts from this address. Wait a minute and try again.")
        try:
            normalized = normalize_email(email)
        except InvalidEmailError as exc:
            raise InvalidCredentialsError from exc

        failures = int(await self._store.get(lock_key(normalized)) or 0)
        if failures >= self._policy.lockout_threshold:
            await _failed_login(self._audit, normalized, "locked")
            minutes = self._policy.lockout_seconds // 60
            raise AccountLockedError(f"Too many failed sign-ins. Try again in {minutes} minutes.")

        user = await self._users.find_by_email(normalized)
        password_hash = await self._credentials.password_hash(user.id) if user else None
        verified = await self._hasher.verify(password_hash, password)
        if user is None or not verified or not user.active:
            _ = await self._store.incr(lock_key(normalized), ttl=self._policy.lockout_seconds)
            reason = "invalid_credentials" if user is None or not verified else "disabled"
            await _failed_login(self._audit, normalized, reason)
            raise InvalidCredentialsError("Check your email and password and try again.")

        membership = await self._directory.membership(user.id)
        if membership is None or not membership.active:
            await _failed_login(self._audit, normalized, "not_a_member")
            raise NotAMemberError("Ask an Owner or Administrator for a new invitation.")

        auth_policy = await self._policies.current()
        if not auth_policy.password_allowed(user.id):
            await _failed_login(self._audit, normalized, "sso_required")
            raise SsoRequiredError("Your org signs in through SSO. Use your organization's sign-in button.")

        assert password_hash is not None
        if self._hasher.needs_rehash(password_hash):
            await self._credentials.set_password_hash(user.id, await self._hasher.hash(password))

        methods = await self._factors.methods(user.id)
        if methods or auth_policy.mfa_required_for(membership.org_role):
            enroll = not methods
            challenge = await self._challenges.open(user, enroll=enroll)
            await self._users.commit()  # a rehashed password
            offered = (MfaMethod.TOTP, MfaMethod.WEBAUTHN) if enroll else methods
            return LoginOutcome(
                user=user, mfa=MfaPending(challenge=challenge, methods=tuple(m.value for m in offered), enroll=enroll)
            )
        return LoginOutcome(user=user, issued=await self._finish(user, factor=None))


class _LoginChallengeStep:
    def __init__(
        self,
        users: UserRepository,
        challenges: LoginChallenges,
        factors: SecondFactors,
        policies: AuthPolicies,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._factors = factors
        self._policies = policies

    async def _user(self, token: str) -> tuple[User, bool]:
        challenge = await self._challenges.get(token)
        user = await self._users.get(challenge.user_id) if challenge else None
        if challenge is None or user is None or not user.active:
            raise MfaChallengeExpiredError("Sign in again (the sign-in expired after 5 minutes).")
        if not (await self._policies.current()).password_allowed(user.id):
            raise SsoRequiredError("Your org signs in through SSO. Use your organization's sign-in button.")
        return user, challenge.enroll


class LoginTotpSetup(_LoginChallengeStep):
    """Enrolling an authenticator app while signing in (the policy requires one and the person has none)."""

    async def __call__(self, token: str) -> tuple[str, str]:
        user, enroll = await self._user(token)
        if not enroll:
            raise MfaChallengeExpiredError("This sign-in doesn't need a new factor.")
        return await self._factors.start_totp(user)


class LoginWebAuthnOptions(_LoginChallengeStep):
    """Creation options when enrolling at sign-in, request options when the person has a key."""

    async def __call__(self, token: str) -> dict[str, Any]:
        user, enroll = await self._user(token)
        purpose = LoginChallenges.purpose(token)
        if enroll:
            return await self._factors.registration_options(user, purpose)
        return await self._factors.authentication_options(user.id, purpose)


class CompleteMfaLogin:
    def __init__(
        self,
        users: UserRepository,
        challenges: LoginChallenges,
        factors: SecondFactors,
        policies: AuthPolicies,
        finish: FinishPasswordSignIn,
        store: EphemeralStore,
        audit: AuditLog,
        policy: SignInPolicy,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._factors = factors
        self._policies = policies
        self._finish = finish
        self._store = store
        self._audit = audit
        self._policy = policy

    async def __call__(
        self,
        token: str,
        *,
        code: str | None = None,
        recovery_code: str | None = None,
        webauthn: Mapping[str, Any] | None = None,
        label: str | None = None,
    ) -> LoginOutcome:
        challenge = await self._challenges.get(token)
        user = await self._users.get(challenge.user_id) if challenge else None
        if challenge is None or user is None or not user.active:
            raise MfaChallengeExpiredError("Sign in again (the sign-in expired after 5 minutes).")
        if not (await self._policies.current()).password_allowed(user.id):
            raise SsoRequiredError("Your org signs in through SSO. Use your organization's sign-in button.")
        purpose = LoginChallenges.purpose(token)

        recovery_codes: list[str] = []
        method: MfaMethod | None
        if challenge.enroll:
            factor: Factor | None = None
            if code:
                factor = await self._factors.confirm_totp(user, code, label=label)
            elif webauthn:
                factor = await self._factors.register_webauthn(user, webauthn, label=label, purpose=purpose)
            method = None if factor is None else MfaMethod(factor.kind.value)
            if factor is not None:
                recovery_codes = await self._factors.issue_recovery_codes(user.id)
                _ = await self._audit.record(
                    AuditEntry(
                        action="auth.mfa.enroll",
                        actor=_user_actor(user),
                        resource_kind="user",
                        resource_id=user.id,
                        resource_display=user.email,
                        fields={"factor": factor.kind.value, "label": factor.label},
                    )
                )
        else:
            method = await self._factors.verify(
                user.id, code=code, recovery_code=recovery_code, webauthn=webauthn, purpose=purpose
            )

        if method is None:
            attempts = await self._challenges.failed(token, challenge)
            _ = await self._store.incr(lock_key(user.email), ttl=self._policy.lockout_seconds)
            tried = "webauthn" if webauthn else "recovery_code" if recovery_code else FactorKind.TOTP.value
            _ = await self._audit.record_now(
                AuditEntry(
                    action="auth.mfa.challenge_failed",
                    actor=_user_actor(user),
                    resource_kind="user",
                    resource_id=user.id,
                    resource_display=user.email,
                    decision="denied",
                    fields={"method": tried, "attempts": str(attempts)},
                )
            )
            raise MfaInvalidError(
                "That didn't work. Check the code and try again."
                if attempts < 5  # noqa: PLR2004
                else "Too many tries. Sign in again."
            )
        await self._challenges.close(token)
        issued = await self._finish(user, factor=method)
        return LoginOutcome(user=user, issued=issued, recovery_codes=recovery_codes)


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
    request_id: str = ""
    """SAML: the AuthnRequest id the response must answer (``InResponseTo``)."""


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


class StartSso:
    def __init__(
        self, clients: SignInClients, store: EphemeralStore, policy: SignInPolicy, saml: SamlServiceProvider
    ) -> None:
        self._clients = clients
        self._store = store
        self._policy = policy
        self._saml = saml

    async def __call__(self, provider_id: str, next_path: str | None) -> str:
        config = await self._clients.config(provider_id)
        if config is None:
            raise NotFoundError(f"There is no sign-in provider {provider_id!r}.")
        state = new_token(24)
        if config.protocol is SignInProtocol.SAML:
            assert config.saml is not None
            url, request_id = self._saml.authn_request(
                config.saml, self._policy.service_provider(provider_id), relay_state=state
            )
            payload = {"provider_id": provider_id, "nonce": "", "verifier": "", "next": safe_next(next_path)}
            await self._store.set(
                f"sso:{state}", orjson.dumps({**payload, "request_id": request_id}), ttl=SSO_STATE_TTL
            )
            return url
        client = await self._clients.get(provider_id)
        if client is None:
            raise NotFoundError(f"There is no sign-in provider {provider_id!r}.")
        nonce, verifier = new_token(24), new_token(48)
        payload = {"provider_id": provider_id, "nonce": nonce, "verifier": verifier, "next": safe_next(next_path)}
        await self._store.set(f"sso:{state}", orjson.dumps(payload), ttl=SSO_STATE_TTL)
        return await client.authorization_url(
            redirect_uri=self._policy.callback_url(provider_id),
            state=state,
            nonce=nonce,
            code_challenge=_challenge(verifier),
        )


class FinishSso:
    """What every protocol shares once the provider vouched for someone: admission, JIT, linking, groups, session."""

    def __init__(
        self,
        users: UserRepository,
        externals: ExternalIdentityRepository,
        sessions: Sessions,
        directory: MembershipDirectory,
        audit: AuditLog,
        groups: ExternalGroupsSync,
    ) -> None:
        self._users = users
        self._externals = externals
        self._sessions = sessions
        self._directory = directory
        self._audit = audit
        self._groups = groups

    async def __call__(self, config: ProviderConfig, profile: ExternalProfile) -> tuple[User, IssuedSession]:
        provider_id = config.id
        if not profile.email:
            raise SsoError("email_missing", f"{config.display_name} didn't share an email address.")
        if not profile.email_verified and not config.trust_unverified_email:
            raise SsoError("email_unverified", f"Verify your email address at {config.display_name} first.")
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
            admission = await self._directory.admit(email, jit_allowed=config.jit_allows(email))
            if not admission.allowed:
                reason = admission.reason or "not_invited"
                await self._failed(email, provider_id, reason)
                raise SsoError(reason, "You need an invitation to join this org.")
            if user is None:
                user = await self._users.add(
                    email=email,
                    display_name=clean_display_name(profile.display_name, email),
                    created_via=CreatedVia.SAML if config.protocol is SignInProtocol.SAML else CreatedVia.OIDC,
                )
            await self._directory.join(user, via=f"sso:{provider_id}")
        assert user is not None
        if linked_id is None:
            await self._externals.link(user.id, provider_id, profile)
        claimed = profile.claims.get("groups")
        if isinstance(claimed, list):
            names = [str(group) for group in cast("list[object]", claimed)]
            await self._groups.sync(user.id, provider_id=provider_id, groups=names)

        issued = await self._sessions.issue(user, method=f"sso:{provider_id}")
        await self._users.touch(user.id, utcnow())
        _ = await self._audit.record(
            AuditEntry(
                action="auth.login",
                actor=_user_actor(user),
                resource_kind="user",
                resource_id=user.id,
                resource_display=user.email,
                fields={"method": config.display_name},
            )
        )
        await self._users.commit()
        return user, issued

    async def _failed(self, email: str, provider_id: str, reason: str) -> None:
        await _failed_login(self._audit, email, f"{reason} via {provider_id}")


async def _saved_state(store: EphemeralStore, state: str) -> _SsoState:
    raw = await store.pop(f"sso:{state}")
    if raw is None:
        raise SsoError("state_expired", "The sign-in took too long or was already used. Start again.")
    return _SsoState(**orjson.loads(raw))


class CompleteSso:
    """OIDC and OAuth 2: the provider redirected back with an authorization code."""

    def __init__(self, clients: SignInClients, store: EphemeralStore, policy: SignInPolicy, finish: FinishSso) -> None:
        self._clients = clients
        self._store = store
        self._policy = policy
        self._finish = finish

    async def __call__(self, provider_id: str, code: str, state: str) -> tuple[User, IssuedSession, str]:
        saved = await _saved_state(self._store, state)
        client = await self._clients.get(provider_id)
        if client is None or saved.provider_id != provider_id:
            raise SsoError("state_mismatch", "The sign-in response doesn't belong to this provider.")
        profile = await client.complete(
            redirect_uri=self._policy.callback_url(provider_id),
            code=code,
            code_verifier=saved.verifier,
            nonce=saved.nonce,
        )
        user, issued = await self._finish(client.config, profile)
        return user, issued, saved.next


class CompleteSamlSso:
    """SAML: the IdP posted a ``SAMLResponse`` to the assertion consumer service."""

    def __init__(
        self,
        clients: SignInClients,
        store: EphemeralStore,
        policy: SignInPolicy,
        saml: SamlServiceProvider,
        finish: FinishSso,
    ) -> None:
        self._clients = clients
        self._store = store
        self._policy = policy
        self._saml = saml
        self._finish = finish

    async def __call__(self, provider_id: str, saml_response: str, relay_state: str) -> tuple[User, IssuedSession, str]:
        saved = await _saved_state(self._store, relay_state)
        config = await self._clients.config(provider_id)
        if config is None or config.saml is None or saved.provider_id != provider_id or not saved.request_id:
            raise SsoError("state_mismatch", "The sign-in response doesn't belong to this provider.")
        assertion = self._saml.parse_response(
            config.saml, self._policy.service_provider(provider_id), saml_response, request_id=saved.request_id
        )
        await SamlReplayGuard(self._store).check(provider_id, assertion.id, assertion.not_on_or_after)
        user, issued = await self._finish(config, saml_profile(config.saml, assertion))
        return user, issued, saved.next


class SamlReplayGuard:
    """An assertion id is accepted once, remembered until the assertion expires (plus clock skew)."""

    def __init__(self, store: EphemeralStore) -> None:
        self._store = store

    async def check(self, provider_id: str, assertion_id: str, not_on_or_after: datetime) -> None:
        ttl = max(1.0, (not_on_or_after - utcnow()).total_seconds() + SAML_REPLAY_SKEW_SECONDS)
        key = f"saml:seen:{provider_id}:{hash_token(assertion_id)}"
        if not await self._store.set_if_absent(key, b"1", ttl=ttl):
            raise SsoError("saml_replayed", "This sign-in response was already used. Start again.")
