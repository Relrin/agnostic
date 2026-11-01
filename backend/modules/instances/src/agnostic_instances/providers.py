"""Dependency wiring of the instances module."""

from __future__ import annotations

from datetime import timedelta

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_audit.facade import AuditLog
from agnostic_instances.application.diagnostics import RuntimeAuth
from agnostic_instances.application.ports import (
    InstanceRepository,
    KeyRepository,
    RuntimeClient,
    Signer,
    SnapshotRepository,
)
from agnostic_instances.application.tokens import PrivateKeyCache, TokenPolicy, TokenService
from agnostic_instances.application.use_cases import (
    CheckHealth,
    ConnectInstance,
    DeleteInstance,
    GetConfig,
    GetHealth,
    GetInstance,
    GetKeys,
    InstanceContext,
    Jwks,
    ListInstances,
    ProbeEndpoint,
    Rediscover,
    RefreshAllSnapshots,
    RotateKeys,
    TestConnection,
    UpdateInstance,
    VerifyToken,
)
from agnostic_instances.facade import InstancesFacade, InstancesFacadeImpl
from agnostic_instances.infrastructure.repository import (
    SqlInstanceRepository,
    SqlKeyRepository,
    SqlSnapshotRepository,
)
from agnostic_instances.infrastructure.runtime import HttpRuntimeClient, Rs256Signer
from agnostic_instances.settings import InstancesSettings
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.settings import Settings


class InstancesProvider(Provider):
    scope = Scope.REQUEST

    instances = provide(SqlInstanceRepository, provides=InstanceRepository)
    keys = provide(SqlKeyRepository, provides=KeyRepository)
    snapshots = provide(SqlSnapshotRepository, provides=SnapshotRepository)
    signer = provide(Rs256Signer, provides=Signer, scope=Scope.APP)
    cache = provide(PrivateKeyCache, scope=Scope.APP)
    tokens = provide(TokenService)
    runtime_auth = provide(RuntimeAuth)
    facade = provide(InstancesFacadeImpl, provides=InstancesFacade)

    probe = provide(ProbeEndpoint)
    connect = provide(ConnectInstance)
    rediscover = provide(Rediscover)
    test = provide(TestConnection)
    update = provide(UpdateInstance)
    delete = provide(DeleteInstance)
    list_instances = provide(ListInstances)
    get_instance = provide(GetInstance)
    get_keys = provide(GetKeys)
    rotate = provide(RotateKeys)
    jwks = provide(Jwks)
    verify = provide(VerifyToken)
    health = provide(GetHealth)
    config = provide(GetConfig)
    check_health = provide(CheckHealth)
    refresh = provide(RefreshAllSnapshots)

    @provide(scope=Scope.APP)
    def client(self) -> RuntimeClient:
        return HttpRuntimeClient()

    @provide(scope=Scope.APP)
    def token_policy(self, settings: InstancesSettings, kernel: Settings) -> TokenPolicy:
        return TokenPolicy(
            issuer=settings.issuer or kernel.public_url(), ttl=timedelta(seconds=settings.token_ttl_seconds)
        )

    @provide
    def context(
        self,
        instances: InstanceRepository,
        keys: KeyRepository,
        snapshots: SnapshotRepository,
        client: RuntimeClient,
        signer: Signer,
        box: SecretBox,
        auth: RuntimeAuth,
        cache: PrivateKeyCache,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
        policy: TokenPolicy,
    ) -> InstanceContext:
        return InstanceContext(
            instances=instances,
            keys=keys,
            snapshots=snapshots,
            client=client,
            signer=signer,
            box=box,
            auth=auth,
            cache=cache,
            authorizer=authorizer,
            audit=audit,
            store=store,
            issuer=policy.issuer,
        )
