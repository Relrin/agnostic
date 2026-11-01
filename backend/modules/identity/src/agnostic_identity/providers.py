"""Dependency wiring of the identity module."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_identity.api.resolver import SessionPrincipalResolver
from agnostic_identity.application.account import (
    ConfirmPasswordReset,
    CreateLocalAccount,
    GetMe,
    ListMySessions,
    RequestPasswordReset,
    RevokeMySession,
    UpdateMe,
)
from agnostic_identity.application.ports import (
    CredentialRepository,
    ExternalIdentityRepository,
    PasswordHasher,
    PreferenceRepository,
    SessionRecordRepository,
    SessionStore,
    SignInClients,
    UserRepository,
)
from agnostic_identity.application.sessions import ResolvePrincipal, Sessions
from agnostic_identity.application.signin import CompleteSso, Login, Logout, SignInPolicy, StartSso
from agnostic_identity.domain.users import SessionPolicy
from agnostic_identity.facade import IdentityFacade, IdentityFacadeImpl, SessionCookies
from agnostic_identity.infrastructure.repository import (
    SqlCredentialRepository,
    SqlExternalIdentityRepository,
    SqlPreferenceRepository,
    SqlSessionRecordRepository,
    SqlUserRepository,
)
from agnostic_identity.infrastructure.security import Argon2PasswordHasher, EphemeralSessionStore
from agnostic_identity.infrastructure.signin_clients import SignInClientRegistry
from agnostic_identity.settings import IdentitySettings
from agnostic_kernel.auth import PrincipalResolver
from agnostic_kernel.settings import Settings


class IdentityProvider(Provider):
    scope = Scope.REQUEST

    users = provide(SqlUserRepository, provides=UserRepository)
    credentials = provide(SqlCredentialRepository, provides=CredentialRepository)
    externals = provide(SqlExternalIdentityRepository, provides=ExternalIdentityRepository)
    preferences = provide(SqlPreferenceRepository, provides=PreferenceRepository)
    records = provide(SqlSessionRecordRepository, provides=SessionRecordRepository)
    session_store = provide(EphemeralSessionStore, provides=SessionStore, scope=Scope.APP)
    hasher = provide(Argon2PasswordHasher, provides=PasswordHasher, scope=Scope.APP)

    sessions = provide(Sessions)
    resolve_principal = provide(ResolvePrincipal)
    resolver = provide(SessionPrincipalResolver, provides=PrincipalResolver)

    login = provide(Login)
    logout = provide(Logout)
    start_sso = provide(StartSso)
    complete_sso = provide(CompleteSso)
    get_me = provide(GetMe)
    update_me = provide(UpdateMe)
    create_local_account = provide(CreateLocalAccount)
    request_reset = provide(RequestPasswordReset)
    confirm_reset = provide(ConfirmPasswordReset)
    list_sessions = provide(ListMySessions)
    revoke_session = provide(RevokeMySession)
    facade = provide(IdentityFacadeImpl, provides=IdentityFacade)

    @provide(scope=Scope.APP)
    def sign_in_policy(self, settings: IdentitySettings, kernel: Settings) -> SignInPolicy:
        return SignInPolicy(
            local_login=settings.local_login,
            lockout_threshold=settings.lockout_threshold,
            lockout_seconds=settings.lockout_minutes * 60,
            attempts_per_ip_per_minute=settings.login_attempts_per_ip_per_minute,
            password_min_length=settings.password_min_length,
            password_reset_seconds=settings.password_reset_minutes * 60,
            public_url=kernel.public_url(),
        )

    @provide(scope=Scope.APP)
    def session_cookies(self, settings: IdentitySettings, kernel: Settings) -> SessionCookies:
        return SessionCookies(secure=kernel.secure_cookies(), max_age=int(settings.session_absolute_days * 86400))

    @provide(scope=Scope.APP)
    def session_policy(self, settings: IdentitySettings) -> SessionPolicy:
        return SessionPolicy(
            idle=timedelta(hours=settings.session_idle_hours),
            absolute=timedelta(days=settings.session_absolute_days),
        )

    @provide(scope=Scope.APP)
    async def sign_in_clients(self, settings: IdentitySettings) -> AsyncIterator[SignInClients]:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "agnostic-sso/0.1"}) as http:
            yield SignInClientRegistry(settings.provider_configs(), http)
