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

from agnostic_identity.domain.mfa import Factor, NewWebAuthnCredential, WebAuthnCredential
from agnostic_identity.domain.policy import AuthPolicy
from agnostic_identity.domain.providers import ExternalProfile, ProviderConfig, SamlAssertion, SamlIdp
from agnostic_identity.domain.users import CreatedVia, User, UserStatus, WebSession
from agnostic_kernel.auth import Principal


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
    async def unlink_provider(self, provider_id: str) -> int:
        """Forget every link to a provider (it was deleted; a new provider with the same id is a different IdP)."""
        ...


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
    """Every enabled provider: configured in settings and stored in the database."""

    async def config(self, provider_id: str) -> ProviderConfig | None: ...
    async def get(self, provider_id: str) -> SignInClient | None:
        """The OIDC / OAuth 2 client of a provider (``None`` for SAML providers and unknown ids)."""
        ...

    async def all(self) -> list[ProviderConfig]: ...
    def configured(self) -> list[ProviderConfig]:
        """Providers from settings only (read-only in the app)."""
        ...


@dataclass(frozen=True, slots=True)
class StoredProvider:
    """A provider managed in the app. ``config.client_secret`` is the opened secret."""

    config: ProviderConfig
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class LoginProviderRepository(Protocol):
    async def list(self) -> list[StoredProvider]: ...
    async def get(self, provider_id: str) -> StoredProvider | None: ...
    async def add(self, config: ProviderConfig, *, enabled: bool, created_by: str) -> StoredProvider: ...
    async def save(self, config: ProviderConfig, *, enabled: bool) -> StoredProvider: ...
    async def delete(self, provider_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SpEndpoints:
    """The installation as a SAML service provider, for one provider."""

    entity_id: str
    acs_url: str


@dataclass(frozen=True, slots=True)
class IdpMetadata:
    entity_id: str
    sso_url: str
    certificates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CertificateInfo:
    subject: str
    not_after: datetime
    fingerprint_sha256: str


class SamlServiceProvider(Protocol):
    def authn_request(self, idp: SamlIdp, sp: SpEndpoints, *, relay_state: str) -> tuple[str, str]:
        """The redirect URL to the IdP (HTTP-Redirect binding) and the AuthnRequest id to expect back."""
        ...

    def parse_response(
        self, idp: SamlIdp, sp: SpEndpoints, saml_response: str, *, request_id: str, now: datetime | None = None
    ) -> SamlAssertion:
        """Validate a posted ``SAMLResponse``; raises ``SsoError``. Replay is the caller's job (it has the store)."""
        ...

    def sp_metadata(self, sp: SpEndpoints, *, name_id_format: str) -> str: ...
    def parse_idp_metadata(self, xml: str) -> IdpMetadata:
        """Raises ``ProviderConfigError``."""
        ...

    async def fetch_idp_metadata(self, url: str) -> str:
        """Raises ``ProviderConfigError``."""
        ...

    def normalize_certificate(self, text: str) -> str:
        """PEM (or bare base64 DER) in, PEM out; raises ``ProviderConfigError``."""
        ...

    def describe_certificate(self, pem: str) -> CertificateInfo: ...


class AuthPolicyRepository(Protocol):
    async def load(self) -> AuthPolicy: ...
    async def store(self, policy: AuthPolicy, *, updated_by: str) -> AuthPolicy: ...


class MfaRepository(Protocol):
    """Second factors, kept in ``identity_credentials`` next to the password."""

    async def factors(self, user_id: str) -> list[Factor]: ...
    async def totp_secret(self, user_id: str) -> tuple[str, str] | None:
        """``(factor id, base32 secret)`` of the person's authenticator app."""
        ...

    async def set_totp(self, user_id: str, secret: str, *, label: str) -> Factor:
        """Replaces an existing authenticator app (one per person)."""
        ...

    async def webauthn_credentials(self, user_id: str) -> list[WebAuthnCredential]: ...
    async def add_webauthn(self, user_id: str, credential: NewWebAuthnCredential, *, label: str) -> Factor: ...
    async def update_sign_count(self, factor_id: str, sign_count: int, at: datetime) -> None: ...
    async def mark_used(self, factor_id: str, at: datetime) -> None: ...
    async def remove(self, user_id: str, factor_id: str) -> Factor | None: ...
    async def remove_all(self, user_id: str) -> None:
        """Every factor and recovery code (the last factor went away)."""
        ...

    async def replace_recovery_codes(self, user_id: str, code_hashes: Sequence[str]) -> None: ...
    async def use_recovery_code(self, user_id: str, code_hash: str, at: datetime) -> bool:
        """Consume a recovery code; ``False`` when it doesn't exist or was used."""
        ...

    async def recovery_codes_left(self, user_id: str) -> int: ...


class WebAuthnVerifier(Protocol):
    def registration_options(
        self, *, user_id: str, user_name: str, display_name: str, exclude: Sequence[bytes]
    ) -> tuple[dict[str, Any], bytes]:
        """``PublicKeyCredentialCreationOptions`` as JSON, and the challenge to keep."""
        ...

    def verify_registration(self, credential: Mapping[str, Any], challenge: bytes) -> NewWebAuthnCredential:
        """Raises ``ValueError`` when the response is not valid."""
        ...

    def authentication_options(self, credentials: Sequence[WebAuthnCredential]) -> tuple[dict[str, Any], bytes]: ...
    def credential_id(self, credential: Mapping[str, Any]) -> bytes | None: ...
    def verify_authentication(self, credential: Mapping[str, Any], challenge: bytes, stored: WebAuthnCredential) -> int:
        """The new signature counter; raises ``ValueError`` when the assertion is not valid."""
        ...


@dataclass(frozen=True, slots=True)
class Membership:
    org_role: str
    active: bool


@dataclass(frozen=True, slots=True)
class Admission:
    allowed: bool
    reason: str | None = None
    """``not_invited``, ``domain_not_allowed``, ``seats_full``: shown on the login page."""


class ExternalGroupsSync(Protocol):
    """Implemented by the directory module: the groups an identity provider asserted at sign-in."""

    async def sync(self, user_id: str, *, provider_id: str, groups: Sequence[str]) -> None:
        """Make the person's IdP-claimed group memberships match ``groups``; joins the caller's transaction."""
        ...


class BearerPrincipalResolver(Protocol):
    """Implemented by the service_accounts module: ``Authorization: Bearer agn_pat_…`` tokens."""

    async def resolve(self, token: str, *, ip: str | None) -> Principal | None:
        """The service account behind a gateway token, or ``None`` when it isn't valid (a 401)."""
        ...


class MembershipDirectory(Protocol):
    async def membership(self, user_id: str) -> Membership | None: ...
    async def admit(self, email: str, *, jit_allowed: bool) -> Admission:
        """May a person with this (verified) email join the org: a pending invitation, or JIT provisioning."""
        ...

    async def join(self, user: User, *, via: str) -> None:
        """Make ``user`` a member: accept their pending invitation (role, bindings) or join as Member (JIT)."""
        ...
