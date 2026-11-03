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
from agnostic_identity.application.admin import (
    CreateLoginProvider,
    DeleteLoginProvider,
    GetAuthPolicy,
    GetLoginProvider,
    ListLoginProviders,
    ProviderSpMetadata,
    UpdateAuthPolicy,
    UpdateLoginProvider,
)
from agnostic_identity.application.mfa import (
    ConfirmTotp,
    GetMyMfa,
    LoginChallenges,
    RegenerateRecoveryCodes,
    RemoveFactor,
    SecondFactors,
    SetupTotp,
    VerifyWebAuthnRegistration,
    WebAuthnRegistrationOptions,
)
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import (
    AuthPolicyRepository,
    CredentialRepository,
    ExternalIdentityRepository,
    LoginProviderRepository,
    MfaRepository,
    PasswordHasher,
    PreferenceRepository,
    SamlServiceProvider,
    SessionRecordRepository,
    SessionStore,
    SignInClients,
    UserRepository,
    WebAuthnVerifier,
)
from agnostic_identity.application.sessions import RecentAuth, ResolvePrincipal, Sessions
from agnostic_identity.application.signin import (
    CompleteMfaLogin,
    CompleteSamlSso,
    CompleteSso,
    FinishPasswordSignIn,
    FinishSso,
    Login,
    LoginTotpSetup,
    LoginWebAuthnOptions,
    Logout,
    SignInPolicy,
    StartSso,
)
from agnostic_identity.application.stepup import GetStepUp, StepUp, StepUpWebAuthnOptions
from agnostic_identity.domain.users import SessionPolicy
from agnostic_identity.facade import IdentityFacade, IdentityFacadeImpl, SessionCookies
from agnostic_identity.infrastructure.governance import (
    SqlAuthPolicyRepository,
    SqlLoginProviderRepository,
    SqlMfaRepository,
)
from agnostic_identity.infrastructure.repository import (
    SqlCredentialRepository,
    SqlExternalIdentityRepository,
    SqlPreferenceRepository,
    SqlSessionRecordRepository,
    SqlUserRepository,
)
from agnostic_identity.infrastructure.saml import XmlSamlServiceProvider
from agnostic_identity.infrastructure.security import Argon2PasswordHasher, EphemeralSessionStore
from agnostic_identity.infrastructure.signin_clients import SignInClientRegistry, SignInDirectory, SsoHttp
from agnostic_identity.infrastructure.webauthn import PyWebAuthnVerifier
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
    login_providers = provide(SqlLoginProviderRepository, provides=LoginProviderRepository)
    auth_policy_repository = provide(SqlAuthPolicyRepository, provides=AuthPolicyRepository)
    mfa_repository = provide(SqlMfaRepository, provides=MfaRepository)
    session_store = provide(EphemeralSessionStore, provides=SessionStore, scope=Scope.APP)
    hasher = provide(Argon2PasswordHasher, provides=PasswordHasher, scope=Scope.APP)
    saml = provide(XmlSamlServiceProvider, provides=SamlServiceProvider, scope=Scope.APP)
    sign_in_clients = provide(SignInDirectory, provides=SignInClients)

    policies = provide(AuthPolicies)
    sessions = provide(Sessions)
    recent_auth = provide(RecentAuth)
    resolve_principal = provide(ResolvePrincipal)
    resolver = provide(SessionPrincipalResolver, provides=PrincipalResolver)
    second_factors = provide(SecondFactors)
    login_challenges = provide(LoginChallenges)

    login = provide(Login)
    finish_password_sign_in = provide(FinishPasswordSignIn)
    complete_mfa_login = provide(CompleteMfaLogin)
    login_totp_setup = provide(LoginTotpSetup)
    login_webauthn_options = provide(LoginWebAuthnOptions)
    logout = provide(Logout)
    start_sso = provide(StartSso)
    finish_sso = provide(FinishSso)
    complete_sso = provide(CompleteSso)
    complete_saml_sso = provide(CompleteSamlSso)
    get_me = provide(GetMe)
    update_me = provide(UpdateMe)
    create_local_account = provide(CreateLocalAccount)
    request_reset = provide(RequestPasswordReset)
    confirm_reset = provide(ConfirmPasswordReset)
    list_sessions = provide(ListMySessions)
    revoke_session = provide(RevokeMySession)

    get_my_mfa = provide(GetMyMfa)
    setup_totp = provide(SetupTotp)
    confirm_totp = provide(ConfirmTotp)
    webauthn_registration_options = provide(WebAuthnRegistrationOptions)
    verify_webauthn_registration = provide(VerifyWebAuthnRegistration)
    remove_factor = provide(RemoveFactor)
    regenerate_recovery_codes = provide(RegenerateRecoveryCodes)
    get_step_up = provide(GetStepUp)
    step_up = provide(StepUp)
    step_up_webauthn_options = provide(StepUpWebAuthnOptions)

    list_login_providers = provide(ListLoginProviders)
    get_login_provider = provide(GetLoginProvider)
    create_login_provider = provide(CreateLoginProvider)
    update_login_provider = provide(UpdateLoginProvider)
    delete_login_provider = provide(DeleteLoginProvider)
    provider_sp_metadata = provide(ProviderSpMetadata)
    get_auth_policy = provide(GetAuthPolicy)
    update_auth_policy = provide(UpdateAuthPolicy)

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
        """The installation default; the org auth policy can override both lifetimes."""
        return SessionPolicy(
            idle=timedelta(hours=settings.session_idle_hours),
            absolute=timedelta(days=settings.session_absolute_days),
        )

    @provide(scope=Scope.APP)
    async def sso_http(self) -> AsyncIterator[SsoHttp]:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": "agnostic-sso/0.1"}) as http:
            yield SsoHttp(http)

    @provide(scope=Scope.APP)
    def sign_in_registry(self, settings: IdentitySettings, http: SsoHttp) -> SignInClientRegistry:
        return SignInClientRegistry(settings.provider_configs(), http)

    @provide(scope=Scope.APP)
    def webauthn(self, kernel: Settings) -> WebAuthnVerifier:
        return PyWebAuthnVerifier(kernel.public_url())
