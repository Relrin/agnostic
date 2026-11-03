"""Dependency wiring of the service_accounts module."""

from __future__ import annotations

import hashlib

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_access.facade import AccessFacade
from agnostic_audit.facade import AuditLog
from agnostic_identity.facade import BearerPrincipalResolver, IdentityFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.crypto import load_master_key
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.settings import Settings
from agnostic_service_accounts.application.accounts import ServiceAccounts
from agnostic_service_accounts.application.ports import RecentAuthentication, ServiceAccountRepository
from agnostic_service_accounts.application.tokens import GatewayTokenResolver, TokenHashing
from agnostic_service_accounts.facade import ServiceAccountsFacade, ServiceAccountsFacadeImpl
from agnostic_service_accounts.infrastructure.identity import IdentityRecentAuthentication
from agnostic_service_accounts.infrastructure.repository import SqlServiceAccountRepository
from agnostic_service_accounts.settings import ServiceAccountsSettings

PEPPER_CONTEXT = b"agnostic/service-accounts/gateway-token-pepper/v1:"


def token_pepper(settings: Settings, module: ServiceAccountsSettings) -> str:
    """The configured pepper, or one derived from the master key (stable across restarts without config)."""
    if module.token_pepper is not None:
        return module.token_pepper.get_secret_value()
    master = load_master_key(settings.secrets, environment=settings.env)
    return hashlib.sha256(PEPPER_CONTEXT + master).hexdigest()


class ServiceAccountsProvider(Provider):
    scope = Scope.REQUEST

    bearer = provide(GatewayTokenResolver, provides=BearerPrincipalResolver)
    recent = provide(IdentityRecentAuthentication, provides=RecentAuthentication)
    facade = provide(ServiceAccountsFacadeImpl, provides=ServiceAccountsFacade)

    @provide
    def accounts(self, session: AsyncSession) -> ServiceAccountRepository:
        return SqlServiceAccountRepository(session)

    @provide(scope=Scope.APP)
    def hashing(self, settings: Settings, module: ServiceAccountsSettings) -> TokenHashing:
        return TokenHashing(pepper=token_pepper(settings, module), touch_every_seconds=module.last_used_write_seconds)

    @provide
    def service_accounts(
        self,
        accounts: ServiceAccountRepository,
        access: AccessFacade,
        instances: InstancesFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        events: DomainEvents,
        recent: RecentAuthentication,
        identity: IdentityFacade,
        hashing: TokenHashing,
        store: EphemeralStore,
        settings: Settings,
    ) -> ServiceAccounts:
        return ServiceAccounts(
            accounts,
            access,
            instances,
            authorizer,
            audit,
            events,
            recent,
            identity,
            hashing,
            store,
            public_url=settings.public_url(),
        )
