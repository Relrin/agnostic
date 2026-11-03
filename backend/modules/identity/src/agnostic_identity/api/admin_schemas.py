"""Request and response bodies of ``/api/v1/auth/admin`` (sign-in providers and the org auth policy)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_identity.application.admin import PolicyView, ProviderView

PresetName = Literal["github", "gitlab", "google", "okta", "oidc", "saml"]
MfaPolicyName = Literal["off", "optional", "required_local", "required_admins"]


class AttributeMappingIn(BaseModel):
    email: str | None = Field(default=None, max_length=300, examples=["email"])
    name: str | None = Field(default=None, max_length=300, examples=["displayName"])
    groups: str | None = Field(default=None, max_length=300, examples=["groups"])


class _ProviderFields(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    allowed_email_domains: list[str] | None = Field(default=None, max_length=50)
    jit_provisioning: bool | None = None
    trust_unverified_email: bool | None = None
    # OIDC / OAuth 2
    issuer: str | None = Field(default=None, max_length=500, description="OIDC issuer (discovery) URL")
    base_url: str | None = Field(default=None, max_length=500, description="GitHub Enterprise Server URL")
    client_id: str | None = Field(default=None, max_length=300)
    client_secret: str | None = Field(
        default=None, max_length=2000, description="Write-only; omit to keep the current one, null to remove it"
    )
    scopes: list[str] | None = Field(default=None, max_length=30)
    # SAML 2.0
    metadata_url: str | None = Field(default=None, max_length=1000, description="IdP metadata URL (fetched now)")
    metadata_xml: str | None = Field(default=None, max_length=2_000_000, description="IdP metadata XML (not kept)")
    idp_entity_id: str | None = Field(default=None, max_length=500)
    sso_url: str | None = Field(default=None, max_length=1000, description="IdP SSO URL (HTTP-Redirect binding)")
    certificates: list[str] | None = Field(default=None, max_length=10, description="IdP signing certificates (PEM)")
    name_id_format: str | None = Field(default=None, max_length=200)
    attribute_mapping: AttributeMappingIn | None = None


class ProviderCreate(_ProviderFields):
    id: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9-]+$", examples=["okta"])
    kind: Literal["oidc", "saml"]
    preset: PresetName | None = Field(default=None, description="Defaults to 'oidc' or 'saml' by kind")

    def values(self) -> dict[str, object]:
        values = self.model_dump(exclude_unset=True, exclude={"id", "metadata_xml"})
        values["kind"] = self.kind
        values["preset"] = self.preset or ("saml" if self.kind == "saml" else "oidc")
        return values


class ProviderUpdate(_ProviderFields):
    preset: PresetName | None = None
    refresh_metadata: bool = Field(default=False, description="SAML: fetch the metadata URL again")

    def changes(self) -> dict[str, object]:
        return self.model_dump(exclude_unset=True, exclude={"metadata_xml", "refresh_metadata"})


class AttributeMappingOut(BaseModel):
    email: str | None
    name: str | None
    groups: str | None


class CertificateOut(BaseModel):
    subject: str
    not_after: datetime
    fingerprint_sha256: str


class OidcSettingsOut(BaseModel):
    issuer: str | None
    base_url: str | None
    client_id: str
    has_client_secret: bool
    scopes: list[str]
    callback_url: str
    """The redirect URI to register at the provider."""


class SamlSettingsOut(BaseModel):
    idp_entity_id: str
    sso_url: str
    metadata_url: str | None
    name_id_format: str
    attribute_mapping: AttributeMappingOut
    certificates: list[CertificateOut]
    sp_entity_id: str
    """Register at the IdP as the SP entity ID / audience; it is also the public SP metadata URL."""
    acs_url: str
    """Register at the IdP as the assertion consumer service (HTTP-POST)."""


class ProviderOut(BaseModel):
    id: str
    kind: Literal["oidc", "saml"]
    preset: PresetName
    display_name: str
    enabled: bool
    managed_by: Literal["config", "database"]
    """``config``: from AGNOSTIC_IDENTITY__PROVIDERS__* (read-only here)."""
    allowed_email_domains: list[str]
    jit_provisioning: bool
    trust_unverified_email: bool
    oidc: OidcSettingsOut | None
    saml: SamlSettingsOut | None
    created_by: str | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_view(cls, view: ProviderView) -> ProviderOut:
        config = view.config
        oidc = saml = None
        if config.saml is None:
            oidc = OidcSettingsOut(
                issuer=config.issuer,
                base_url=config.base_url,
                client_id=config.client_id,
                has_client_secret=view.has_client_secret,
                scopes=list(config.scopes),
                callback_url=view.callback_url or "",
            )
        else:
            idp = config.saml
            sp = view.service_provider
            assert sp is not None
            saml = SamlSettingsOut(
                idp_entity_id=idp.entity_id,
                sso_url=idp.sso_url,
                metadata_url=idp.metadata_url,
                name_id_format=idp.name_id_format,
                attribute_mapping=AttributeMappingOut(
                    email=idp.attributes.email, name=idp.attributes.name, groups=idp.attributes.groups
                ),
                certificates=[
                    CertificateOut(
                        subject=item.subject, not_after=item.not_after, fingerprint_sha256=item.fingerprint_sha256
                    )
                    for item in view.certificates
                ],
                sp_entity_id=sp.entity_id,
                acs_url=sp.acs_url,
            )
        return cls(
            id=config.id,
            kind=config.kind.value,
            preset=config.preset.value,
            display_name=config.display_name,
            enabled=view.enabled,
            managed_by=view.managed_by.value,
            allowed_email_domains=list(config.allowed_email_domains),
            jit_provisioning=config.jit_provisioning,
            trust_unverified_email=config.trust_unverified_email,
            oidc=oidc,
            saml=saml,
            created_by=view.created_by,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )


class BreakGlassUserOut(BaseModel):
    id: str
    email: str
    display_name: str


class AuthPolicyOut(BaseModel):
    enforce_sso: bool
    break_glass_user_id: str | None
    break_glass_user: BreakGlassUserOut | None
    session_idle_minutes: int | None
    """``null``: the installation default (``default_session_idle_minutes``)."""
    session_absolute_hours: int | None
    """``null``: the installation default (``default_session_absolute_hours``)."""
    default_session_idle_minutes: int
    default_session_absolute_hours: int
    mfa_policy: MfaPolicyName
    updated_by: str | None
    updated_at: datetime | None

    @classmethod
    def from_view(cls, view: PolicyView) -> AuthPolicyOut:
        policy = view.policy
        user = view.break_glass_user
        return cls(
            enforce_sso=policy.enforce_sso,
            break_glass_user_id=policy.break_glass_user_id,
            break_glass_user=BreakGlassUserOut(id=user.id, email=user.email, display_name=user.display_name)
            if user
            else None,
            session_idle_minutes=policy.session_idle_minutes,
            session_absolute_hours=policy.session_absolute_hours,
            default_session_idle_minutes=int(view.defaults.idle.total_seconds() // 60),
            default_session_absolute_hours=int(view.defaults.absolute.total_seconds() // 3600),
            mfa_policy=policy.mfa_policy.value,
            updated_by=policy.updated_by,
            updated_at=policy.updated_at,
        )


class AuthPolicyUpdate(BaseModel):
    enforce_sso: bool = False
    break_glass_user_id: str | None = Field(default=None, max_length=40)
    session_idle_minutes: int | None = Field(default=None, ge=5, le=43200)
    session_absolute_hours: int | None = Field(default=None, ge=1, le=2160)
    mfa_policy: MfaPolicyName = "optional"
