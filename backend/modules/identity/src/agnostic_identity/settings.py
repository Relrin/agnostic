"""``AGNOSTIC_IDENTITY__*`` settings.

Sign-in providers are configured per id, e.g. GitHub and Okta::

    AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__PRESET=github
    AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_ID=Iv1.0123456789abcdef
    AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_SECRET=...
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__PRESET=okta
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__ISSUER=https://localhost-company.okta.com/oauth2/default
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__CLIENT_ID=...
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__CLIENT_SECRET=...
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__JIT_PROVISIONING=true
    AGNOSTIC_IDENTITY__PROVIDERS__OKTA__ALLOWED_EMAIL_DOMAINS=localhost.company

The callback URL to register at the provider is ``{public_url}/api/v1/auth/sso/<id>/callback``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode

from agnostic_identity.domain.providers import Preset, ProviderConfig, resolve_provider
from agnostic_kernel.settings import module_settings_config


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class SignInProviderSettings(BaseModel):
    preset: Preset = Preset.OIDC
    display_name: str | None = None
    client_id: str
    client_secret: SecretStr | None = None
    issuer: str | None = None
    """OIDC issuer (Okta: ``https://<org>.okta.com/oauth2/default``; any OIDC IdP: its issuer URL;
    self-managed GitLab: its URL). Google and gitlab.com need none."""
    base_url: str | None = None
    """GitHub Enterprise Server URL (``https://github.example.com``) or a self-managed GitLab's URL
    (``https://gitlab.example.com``, which is also its issuer); github.com and gitlab.com need none."""
    scopes: Annotated[list[str], NoDecode] = []
    allowed_email_domains: Annotated[list[str], NoDecode] = []
    jit_provisioning: bool = False
    """Let people from ``allowed_email_domains`` join as Members on first sign-in, without an invitation."""
    trust_unverified_email: bool = False
    enabled: bool = True

    _split_scopes = field_validator("scopes", mode="before")(_split_csv)
    _split_domains = field_validator("allowed_email_domains", mode="before")(_split_csv)


class IdentitySettings(BaseSettings):
    model_config = module_settings_config("identity")

    local_login: bool = True
    """Email + password accounts. Convenient for single-person and small installs; turn off to require SSO."""
    providers: dict[str, SignInProviderSettings] = {}
    password_min_length: int = Field(default=12, ge=8)
    session_idle_hours: float = Field(default=12, gt=0)
    session_absolute_days: float = Field(default=7, gt=0)
    lockout_threshold: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)
    login_attempts_per_ip_per_minute: int = Field(default=30, ge=1)
    password_reset_minutes: int = Field(default=60, ge=5)

    def provider_configs(self) -> list[ProviderConfig]:
        return [
            resolve_provider(
                provider_id,
                preset=item.preset,
                client_id=item.client_id,
                client_secret=item.client_secret.get_secret_value() if item.client_secret else None,
                display_name=item.display_name,
                issuer=item.issuer,
                base_url=item.base_url,
                scopes=item.scopes or None,
                allowed_email_domains=item.allowed_email_domains,
                jit_provisioning=item.jit_provisioning,
                trust_unverified_email=item.trust_unverified_email,
            )
            for provider_id, item in sorted(self.providers.items())
            if item.enabled
        ]
