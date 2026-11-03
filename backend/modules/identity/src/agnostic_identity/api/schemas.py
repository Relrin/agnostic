"""Request and response bodies of ``/api/v1/auth`` and ``/api/v1/me``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_identity.application.account import MeView
from agnostic_identity.application.mfa import Enrolled, MfaStatus
from agnostic_identity.application.stepup import StepUpStatus
from agnostic_identity.domain.mfa import Factor
from agnostic_identity.domain.users import WebSession


class LoginRequest(BaseModel):
    email: str = Field(max_length=320, examples=["daniel@localhost.company"])
    password: str = Field(max_length=1024)


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=320)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=1024)


class SignInProviderOut(BaseModel):
    id: str
    display_name: str
    preset: Literal["github", "gitlab", "google", "okta", "oidc", "saml"]


class AuthOptions(BaseModel):
    local_login: bool
    sso_enforced: bool = False
    """Password sign-in is reserved for the break-glass Owner; show the SSO buttons first."""
    providers: list[SignInProviderOut]


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_seed: str
    locale: str | None
    timezone: str | None
    org_role: Literal["owner", "administrator", "member"] | None
    preferences: dict[str, Any]
    has_password: bool
    sso_providers: list[str]
    session_method: str | None
    created_at: datetime
    last_active_at: datetime | None

    @classmethod
    def from_view(cls, view: MeView) -> MeOut:
        user = view.user
        role = view.org_role if view.org_role in {"owner", "administrator", "member"} else None
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_seed=user.avatar_seed,
            locale=user.locale,
            timezone=user.timezone,
            org_role=role,  # pyright: ignore[reportArgumentType]
            preferences=view.preferences,
            has_password=view.has_password,
            sso_providers=view.sso_providers,
            session_method=view.session_method,
            created_at=user.created_at,
            last_active_at=user.last_active_at,
        )


class SignedIn(BaseModel):
    user: MeOut
    csrf_token: str


class MfaRequired(BaseModel):
    """``POST /auth/login`` when a second factor is needed: no session yet, answer at ``POST /auth/login/mfa``."""

    mfa_required: Literal[True] = True
    challenge: str
    """Single-use, valid for 5 minutes and 5 wrong answers."""
    methods: list[Literal["totp", "webauthn", "recovery_code"]]
    enroll: bool
    """The org requires a second factor and the person has none: set one up first (``/auth/login/mfa/totp/setup``
    or ``/auth/login/mfa/webauthn/options``), then confirm it at ``/auth/login/mfa``."""


class LoginMfaRequest(BaseModel):
    challenge: str = Field(min_length=10, max_length=200)
    code: str | None = Field(default=None, max_length=12, description="Authenticator app code")
    recovery_code: str | None = Field(default=None, max_length=40)
    webauthn: dict[str, Any] | None = Field(
        default=None, description="The PublicKeyCredential as JSON (assertion, or attestation when enrolling)"
    )
    label: str | None = Field(default=None, max_length=120, description="When enrolling: the factor's name")


class LoginChallengeRequest(BaseModel):
    challenge: str = Field(min_length=10, max_length=200)


class MfaSignedIn(SignedIn):
    recovery_codes: list[str] = []
    """Shown once, when a factor was enrolled while signing in."""


class FactorOut(BaseModel):
    id: str
    kind: Literal["totp", "webauthn"]
    label: str
    created_at: datetime
    last_used_at: datetime | None

    @classmethod
    def from_domain(cls, factor: Factor) -> FactorOut:
        return cls(
            id=factor.id,
            kind=factor.kind.value,
            label=factor.label,
            created_at=factor.created_at,
            last_used_at=factor.last_used_at,
        )


class MfaOut(BaseModel):
    policy: Literal["off", "optional", "required_local", "required_admins"]
    required: bool
    factors: list[FactorOut]
    recovery_codes_left: int

    @classmethod
    def from_status(cls, status: MfaStatus) -> MfaOut:
        return cls(
            policy=status.policy.value,
            required=status.required,
            factors=[FactorOut.from_domain(item) for item in status.factors],
            recovery_codes_left=status.recovery_codes_left,
        )


class TotpSetupOut(BaseModel):
    secret: str
    """Base32, for typing in by hand."""
    otpauth_uri: str
    """Render as a QR code."""


class TotpConfirm(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    label: str | None = Field(default=None, max_length=120)


class WebAuthnVerify(BaseModel):
    credential: dict[str, Any] = Field(description="The PublicKeyCredential from navigator.credentials.create()")
    label: str | None = Field(default=None, max_length=120)


class EnrolledOut(BaseModel):
    factor: FactorOut
    recovery_codes: list[str]
    """New recovery codes when this was the first factor (shown once), otherwise empty."""

    @classmethod
    def from_domain(cls, enrolled: Enrolled) -> EnrolledOut:
        return cls(factor=FactorOut.from_domain(enrolled.factor), recovery_codes=enrolled.recovery_codes)


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class StepUpRequest(BaseModel):
    password: str | None = Field(default=None, max_length=1024)
    code: str | None = Field(default=None, max_length=12)
    webauthn: dict[str, Any] | None = None


class StepUpOut(BaseModel):
    authenticated_at: datetime | None
    recent: bool
    """Sensitive changes are allowed until ``expires_at`` (10 minutes after the last sign-in or step-up)."""
    expires_at: datetime | None
    methods: list[str]
    """``password``, ``totp``, ``webauthn``, and ``sso`` (sign in again through one of ``sso_providers``)."""
    sso_providers: list[str]

    @classmethod
    def from_status(cls, status: StepUpStatus) -> StepUpOut:
        return cls(
            authenticated_at=status.authenticated_at,
            recent=status.recent,
            expires_at=status.expires_at,
            methods=list(status.methods),
            sso_providers=list(status.sso_providers),
        )


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    locale: str | None = Field(default=None, max_length=35)
    timezone: str | None = Field(default=None, max_length=64)
    preferences: dict[str, Any] | None = Field(default=None, examples=[{"api_hints": True}])


class SessionOut(BaseModel):
    id: str
    method: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    current: bool

    @classmethod
    def from_domain(cls, session: WebSession, current_key: str | None) -> SessionOut:
        return cls(
            id=session.key,
            method=session.method,
            ip=session.ip,
            user_agent=session.user_agent,
            created_at=session.created_at,
            current=session.key == current_key,
        )
