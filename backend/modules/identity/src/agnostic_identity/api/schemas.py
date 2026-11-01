"""Request and response bodies of ``/api/v1/auth`` and ``/api/v1/me``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_identity.application.account import MeView
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
    preset: Literal["github", "gitlab", "google", "okta", "oidc"]


class AuthOptions(BaseModel):
    local_login: bool
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
