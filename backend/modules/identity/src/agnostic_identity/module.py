"""Module declaration: identity (accounts, sign-in, sessions)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_identity.api.router import auth_router, me_router
from agnostic_identity.infrastructure.tables import IdentityBase
from agnostic_identity.providers import IdentityProvider
from agnostic_identity.settings import IdentitySettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec


class IdentityModule(BaseModule):
    name = "identity"
    version = "0.1.0"
    depends_on = ("audit",)

    def settings_model(self) -> type[BaseSettings] | None:
        return IdentitySettings

    def provide(self) -> Iterable[Provider]:
        return (IdentityProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=auth_router, prefix="/auth", tags=("auth",)),
            RouterSpec(router=me_router, prefix="/me", tags=("me",)),
        )

    def metadata(self) -> MetaData | None:
        return IdentityBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("auth.login", "{actor} signed in ({method})"),
            AuditActionDecl("auth.login_failed", "Sign-in failed for {email}: {reason}"),
            AuditActionDecl("auth.logout", "{actor} signed out"),
            AuditActionDecl("auth.password_reset_requested", "A password reset was requested for {resource}"),
            AuditActionDecl("auth.password_reset", "{actor} reset their password"),
        )
