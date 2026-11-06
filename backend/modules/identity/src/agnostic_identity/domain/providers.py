"""Sign-in providers: presets for well-known identity providers. Pure data.

Three protocols cover them:

- **OIDC** (GitLab, Google, Okta, Microsoft Entra ID, Authentik, Dex, ...): discovery document, authorization
  code + PKCE, a signed ``id_token`` with ``nonce``.
- **OAuth 2 + user API** (GitHub): GitHub has no OIDC for signing people in, so the profile comes from its REST API
  (``/user`` and the verified primary address from ``/user/emails``).
- **SAML 2.0** (any IdP without OIDC, or where SAML is the house standard): SP-initiated, an HTTP-Redirect
  AuthnRequest, and a signed response posted back to the assertion consumer service.

Providers come from settings (read-only, ``managed_by=config``) or from the database (managed in the app).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

PROVIDER_ID = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


class SignInProtocol(StrEnum):
    OIDC = "oidc"
    GITHUB = "github"
    SAML = "saml"


class ProviderKind(StrEnum):
    """How a provider is stored: ``oidc`` covers the OIDC and OAuth 2 presets (GitHub too), ``saml`` is SAML 2.0."""

    OIDC = "oidc"
    SAML = "saml"


class ManagedBy(StrEnum):
    CONFIG = "config"
    """``AGNOSTIC_IDENTITY__PROVIDERS__*``: read-only in the app."""
    DATABASE = "database"


class Preset(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    GOOGLE = "google"
    OKTA = "okta"
    OIDC = "oidc"
    SAML = "saml"


@dataclass(frozen=True, slots=True)
class PresetSpec:
    protocol: SignInProtocol
    display_name: str
    default_issuer: str | None
    """For OIDC presets; ``None`` means the operator must configure the issuer (tenant-specific IdPs)."""
    default_base_url: str | None
    """For GitHub: ``https://github.com`` or a GitHub Enterprise Server URL."""
    scopes: tuple[str, ...]
    extra_authorize_params: Mapping[str, str] = field(default_factory=dict[str, str])


PRESETS: Mapping[Preset, PresetSpec] = {
    Preset.GITHUB: PresetSpec(SignInProtocol.GITHUB, "GitHub", None, "https://github.com", ("read:user", "user:email")),
    Preset.GITLAB: PresetSpec(
        SignInProtocol.OIDC, "GitLab", "https://gitlab.com", None, ("openid", "profile", "email")
    ),
    Preset.GOOGLE: PresetSpec(
        SignInProtocol.OIDC,
        "Google",
        "https://accounts.google.com",
        None,
        ("openid", "profile", "email"),
        {"prompt": "select_account"},
    ),
    Preset.OKTA: PresetSpec(SignInProtocol.OIDC, "Okta", None, None, ("openid", "profile", "email")),
    Preset.OIDC: PresetSpec(SignInProtocol.OIDC, "Single sign-on", None, None, ("openid", "profile", "email")),
    Preset.SAML: PresetSpec(SignInProtocol.SAML, "SAML single sign-on", None, None, ()),
}

NAME_ID_UNSPECIFIED = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
NAME_ID_EMAIL = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
NAME_ID_PERSISTENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
NAME_ID_FORMATS = (
    NAME_ID_UNSPECIFIED,
    NAME_ID_EMAIL,
    NAME_ID_PERSISTENT,
    "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
)

# Attribute names IdPs commonly use, tried in order when the mapping doesn't name one.
DEFAULT_EMAIL_ATTRIBUTES = (
    "email",
    "mail",
    "emailAddress",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "urn:oid:0.9.2342.19200300.100.1.3",
)
DEFAULT_NAME_ATTRIBUTES = (
    "displayName",
    "name",
    "http://schemas.microsoft.com/identity/claims/displayname",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    "urn:oid:2.16.840.1.113730.3.1.241",
)
DEFAULT_GROUPS_ATTRIBUTES = (
    "groups",
    "memberOf",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
    "urn:oid:1.3.6.1.4.1.5923.1.5.1.1",
)


@dataclass(frozen=True, slots=True)
class AttributeMapping:
    """Which SAML attributes carry the email, display name and groups (``None``: try the common names)."""

    email: str | None = None
    name: str | None = None
    groups: str | None = None


@dataclass(frozen=True, slots=True)
class SamlIdp:
    entity_id: str
    sso_url: str
    """The IdP's SingleSignOnService location for the HTTP-Redirect binding."""
    certificates: tuple[str, ...]
    """PEM signing certificates; any of them may sign (so a rotation can overlap)."""
    metadata_url: str | None = None
    name_id_format: str = NAME_ID_UNSPECIFIED
    attributes: AttributeMapping = field(default_factory=AttributeMapping)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """A configured sign-in provider (from ``AGNOSTIC_IDENTITY__PROVIDERS__<ID>__*`` or the database)."""

    id: str
    preset: Preset
    display_name: str
    client_id: str
    client_secret: str | None
    issuer: str | None
    base_url: str | None
    scopes: tuple[str, ...]
    allowed_email_domains: tuple[str, ...]
    jit_provisioning: bool
    trust_unverified_email: bool
    extra_authorize_params: Mapping[str, str]
    saml: SamlIdp | None = None
    managed_by: ManagedBy = ManagedBy.CONFIG
    version: str = ""
    """Changes whenever a stored provider changes (clients built from it are cached per version)."""

    @property
    def protocol(self) -> SignInProtocol:
        return PRESETS[self.preset].protocol

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.SAML if self.protocol is SignInProtocol.SAML else ProviderKind.OIDC

    def jit_allows(self, email: str) -> bool:
        """New people may join without an invitation only through JIT, and only from allowed domains."""
        if not self.jit_provisioning:
            return False
        domain = email.rsplit("@", 1)[-1].lower()
        return not self.allowed_email_domains or domain in self.allowed_email_domains


class ProviderConfigError(ValueError):
    pass


def _gitlab_urls(issuer: str | None, base_url: str | None) -> tuple[str | None, str | None]:
    """GitLab's OIDC issuer is the instance URL (its ``external_url``), so the two are one setting.

    The instance URL wins: a provider stored with the gitlab.com default issuer next to a
    self-managed URL signs in against the self-managed instance. An issuer given alone (the
    older way to point at a self-managed GitLab) still works and becomes the instance URL.
    """
    url = (base_url or "").strip().rstrip("/") or (issuer or "").strip().rstrip("/") or None
    default = PRESETS[Preset.GITLAB].default_issuer
    if url is None or url == default:
        return default, None
    return url, url


def resolve_provider(
    provider_id: str,
    *,
    preset: Preset,
    client_id: str,
    client_secret: str | None,
    display_name: str | None = None,
    issuer: str | None = None,
    base_url: str | None = None,
    scopes: Sequence[str] | None = None,
    allowed_email_domains: Sequence[str] = (),
    jit_provisioning: bool = False,
    trust_unverified_email: bool = False,
    saml: SamlIdp | None = None,
    managed_by: ManagedBy = ManagedBy.CONFIG,
    version: str = "",
) -> ProviderConfig:
    spec = PRESETS[preset]
    if preset is Preset.GITLAB:
        issuer, base_url = _gitlab_urls(issuer, base_url)
    resolved_issuer = (issuer or spec.default_issuer or "").rstrip("/") or None
    if spec.protocol is SignInProtocol.OIDC and resolved_issuer is None:
        raise ProviderConfigError(f"sign-in provider {provider_id!r} ({preset.value}) needs an issuer URL")
    if spec.protocol is SignInProtocol.SAML:
        _ = check_saml_idp(saml)
    elif not client_id:
        raise ProviderConfigError(f"sign-in provider {provider_id!r} needs a client id")
    extra = dict(spec.extra_authorize_params)
    domains = clean_domains(allowed_email_domains)
    if preset is Preset.GOOGLE and len(domains) == 1:
        extra["hd"] = domains[0]  # Google Workspace: preselect the hosted domain
    return ProviderConfig(
        id=provider_id,
        preset=preset,
        display_name=display_name or spec.display_name,
        client_id=client_id,
        client_secret=client_secret,
        issuer=resolved_issuer,
        base_url=(base_url or spec.default_base_url or "").rstrip("/") or None,
        scopes=tuple(scopes) if scopes else spec.scopes,
        allowed_email_domains=domains,
        jit_provisioning=jit_provisioning,
        trust_unverified_email=trust_unverified_email,
        extra_authorize_params=extra,
        saml=saml if spec.protocol is SignInProtocol.SAML else None,
        managed_by=managed_by,
        version=version,
    )


def check_provider_id(provider_id: str) -> str:
    if not PROVIDER_ID.fullmatch(provider_id):
        raise ProviderConfigError(
            "Use 2-40 lowercase letters, digits and dashes, starting with a letter (the id is part of the "
            "callback URL)."
        )
    return provider_id


def check_saml_idp(idp: SamlIdp | None) -> SamlIdp:
    if idp is None:
        raise ProviderConfigError("A SAML provider needs the IdP's metadata (a URL or the XML) or its settings.")
    if not idp.entity_id:
        raise ProviderConfigError("The IdP entity ID is missing.")
    if not idp.sso_url.startswith(("https://", "http://")):
        raise ProviderConfigError("The IdP single sign-on URL must be an http(s) URL (HTTP-Redirect binding).")
    if not idp.certificates:
        raise ProviderConfigError("At least one IdP signing certificate is needed; unsigned responses are refused.")
    if idp.name_id_format not in NAME_ID_FORMATS:
        raise ProviderConfigError(f"Unknown NameID format {idp.name_id_format!r}.")
    return idp


def clean_domains(domains: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(domain.strip().lower().lstrip("@") for domain in domains if domain.strip()))


@dataclass(frozen=True, slots=True)
class ExternalProfile:
    """Who the provider says signed in."""

    subject: str
    email: str | None
    email_verified: bool
    display_name: str | None
    claims: Mapping[str, Any]


class SsoError(Exception):
    """Sign-in through a provider failed; ``code`` goes to the login page (``/login?error=<code>``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SamlAssertion:
    """A validated SAML assertion: only what the signature covered."""

    id: str
    issuer: str
    name_id: str
    name_id_format: str | None
    attributes: Mapping[str, tuple[str, ...]]
    not_on_or_after: datetime
    """When the assertion stops being usable (its id must be remembered until then)."""


def _first(attributes: Mapping[str, tuple[str, ...]], names: Sequence[str]) -> tuple[str, ...]:
    for name in names:
        if values := attributes.get(name):
            return values
    return ()


def saml_profile(idp: SamlIdp, assertion: SamlAssertion) -> ExternalProfile:
    """Map the asserted attributes to a profile. The IdP is trusted to have verified the address it asserts."""
    mapping = idp.attributes
    emails = _first(assertion.attributes, (mapping.email,) if mapping.email else DEFAULT_EMAIL_ATTRIBUTES)
    email = emails[0] if emails else None
    if email is None and assertion.name_id_format == NAME_ID_EMAIL:
        email = assertion.name_id
    names = _first(assertion.attributes, (mapping.name,) if mapping.name else DEFAULT_NAME_ATTRIBUTES)
    groups = _first(assertion.attributes, (mapping.groups,) if mapping.groups else DEFAULT_GROUPS_ATTRIBUTES)
    claims: dict[str, Any] = {"sub": assertion.name_id, "iss": assertion.issuer, "groups": list(groups)}
    if email:
        claims["email"] = email
    if names:
        claims["name"] = names[0]
    return ExternalProfile(
        subject=assertion.name_id,
        email=email,
        email_verified=email is not None,
        display_name=names[0] if names else None,
        claims=claims,
    )
