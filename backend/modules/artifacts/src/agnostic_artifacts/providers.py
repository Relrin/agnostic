"""Dependency wiring of the artefacts module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_artifacts.application.content import ArtifactContent
from agnostic_artifacts.application.ports import ShareRepository
from agnostic_artifacts.application.shares import Shares
from agnostic_artifacts.infrastructure.repository import SqlShareRepository
from agnostic_artifacts.settings import ArtifactsSettings
from agnostic_audit.facade import AuditLog
from agnostic_gateway.facade import GatewayFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer


class ArtifactsProvider(Provider):
    scope = Scope.REQUEST

    repository = provide(SqlShareRepository, provides=ShareRepository)

    @provide
    def content(self, gateway: GatewayFacade, settings: ArtifactsSettings) -> ArtifactContent:
        return ArtifactContent(gateway, settings.max_content_mb)

    @provide
    def shares(
        self,
        content: ArtifactContent,
        instances: InstancesFacade,
        repository: ShareRepository,
        authorizer: Authorizer,
        audit: AuditLog,
        settings: ArtifactsSettings,
    ) -> Shares:
        return Shares(
            content,
            instances,
            repository,
            authorizer,
            audit,
            max_content_mb=settings.max_content_mb,
            max_share_days=settings.max_share_days,
            public_links=settings.public_links,
        )
