"""Module declaration: identity (accounts, sign-in, sessions)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_identity.api.router import admin_router, auth_router, me_router, mfa_router
from agnostic_identity.application.ports import SignInClients
from agnostic_identity.infrastructure.checks import provider_checks
from agnostic_identity.infrastructure.tables import IdentityBase
from agnostic_identity.providers import IdentityProvider
from agnostic_identity.settings import IdentitySettings
from agnostic_kernel.diagnostics import CheckResult
from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec, SealedColumn


class IdentityModule(BaseModule):
    name = "identity"
    version = "0.4.0"
    depends_on = ("audit",)

    def settings_model(self) -> type[BaseSettings] | None:
        return IdentitySettings

    def provide(self) -> Iterable[Provider]:
        return (IdentityProvider(),)

    def sealed_columns(self) -> Iterable[SealedColumn]:
        return (
            SealedColumn("identity_credentials", "secret_hash"),
            SealedColumn("identity_login_providers", "config", json_keys=("client_secret",)),
        )

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=auth_router, prefix="/auth", tags=("auth",)),
            RouterSpec(router=admin_router, prefix="/auth/admin", tags=("auth",)),
            RouterSpec(router=me_router, prefix="/me", tags=("me",)),
            RouterSpec(router=mfa_router, prefix="/me/mfa", tags=("me",)),
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
            AuditActionDecl("auth.break_glass", "{actor} signed in with the break-glass account from {ip}"),
            AuditActionDecl("auth.step_up", "{actor} confirmed it's them ({method})"),
            AuditActionDecl("auth.step_up_failed", "{actor} failed to confirm it's them ({method})"),
            AuditActionDecl("auth.mfa.enroll", "{actor} added a second factor: {label}"),
            AuditActionDecl("auth.mfa.remove", "{actor} removed a second factor: {label}"),
            AuditActionDecl("auth.mfa.recovery_codes", "{actor} generated new recovery codes"),
            AuditActionDecl("auth.mfa.challenge_failed", "A second factor was wrong for {resource} ({method})"),
            AuditActionDecl("auth.providers.create", "{actor} added the sign-in provider {provider} ({kind})"),
            AuditActionDecl("auth.providers.update", "{actor} changed the sign-in provider {provider}: {changes}"),
            AuditActionDecl("auth.providers.delete", "{actor} deleted the sign-in provider {provider}"),
            AuditActionDecl("auth.policy.update", "{actor} changed the authentication policy: {changes}"),
        )

    async def endpoint_checks(self, container: AsyncContainer) -> Sequence[CheckResult]:
        return await provider_checks(await container.get(SignInClients))
