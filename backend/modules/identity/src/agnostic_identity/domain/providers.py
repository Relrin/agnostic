"""Sign-in providers: presets for well-known identity providers. Pure data.

Two protocols cover them:

- **OIDC** (GitLab, Google, Okta, Microsoft Entra ID, Authentik, Dex, ...): discovery document, authorization
  code + PKCE, a signed ``id_token`` with ``nonce``.
- **OAuth 2 + user API** (GitHub): GitHub has no OIDC for signing people in, so the profile comes from its REST API
  (``/user`` and the verified primary address from ``/user/emails``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SignInProtocol(StrEnum):
    OIDC = "oidc"
    GITHUB = "github"


class Preset(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    GOOGLE = "google"
    OKTA = "okta"
    OIDC = "oidc"


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
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """A configured sign-in provider (from ``AGNOSTIC_IDENTITY__PROVIDERS__<ID>__*``)."""

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

    @property
    def protocol(self) -> SignInProtocol:
        return PRESETS[self.preset].protocol

    def jit_allows(self, email: str) -> bool:
        """New people may join without an invitation only through JIT, and only from allowed domains."""
        if not self.jit_provisioning:
            return False
        domain = email.rsplit("@", 1)[-1].lower()
        return not self.allowed_email_domains or domain in self.allowed_email_domains


class ProviderConfigError(ValueError):
    pass


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
) -> ProviderConfig:
    spec = PRESETS[preset]
    resolved_issuer = (issuer or spec.default_issuer or "").rstrip("/") or None
    if spec.protocol is SignInProtocol.OIDC and resolved_issuer is None:
        raise ProviderConfigError(f"sign-in provider {provider_id!r} ({preset.value}) needs an issuer URL")
    extra = dict(spec.extra_authorize_params)
    domains = tuple(domain.lower().lstrip("@") for domain in allowed_email_domains)
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
    )


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
