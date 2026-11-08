"""Module declaration: service accounts (machine identities and their tokens)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_kernel.modules import AuditActionDecl, BaseModule, JobSpec, RouterSpec, ScopeDecl
from agnostic_service_accounts import jobs
from agnostic_service_accounts.api.router import router
from agnostic_service_accounts.infrastructure.tables import ServiceAccountsBase
from agnostic_service_accounts.providers import ServiceAccountsProvider
from agnostic_service_accounts.settings import ServiceAccountsSettings


class ServiceAccountsModule(BaseModule):
    name = "service_accounts"
    version = "0.3.0"
    depends_on = ("access", "audit", "identity", "instances")

    def settings_model(self) -> type[BaseSettings] | None:
        return ServiceAccountsSettings

    def provide(self) -> Iterable[Provider]:
        return (ServiceAccountsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/service-accounts", tags=("service-accounts",)),)

    def metadata(self) -> MetaData | None:
        return ServiceAccountsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (ScopeDecl("service_accounts:manage", "Manage org service accounts"),)

    def jobs(self) -> Iterable[JobSpec]:
        cron = ServiceAccountsSettings().poll_cron
        return (JobSpec(name=jobs.POLL_TASK, func=jobs.poll_last_used, periodic=cron),) if cron else ()

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl(
                "service_accounts.create", "{actor} created the service account {account}: {grant} on {instances}"
            ),
            AuditActionDecl("service_accounts.delete", "{actor} deleted the service account {account}"),
            AuditActionDecl("service_accounts.expire", "The service account {account} expired"),
            AuditActionDecl("tokens.create", "{actor} issued the {kind} token {token} for {account}{where}"),
            AuditActionDecl("tokens.rotate", "{actor} rotated the {kind} token of {account}{where}: new token {token}"),
            AuditActionDecl("tokens.revoke", "{actor} revoked the {kind} token {token} of {account}{where}"),
        )
