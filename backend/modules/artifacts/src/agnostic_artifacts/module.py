"""Module declaration: artefacts, the files agents produce.

The files themselves stay in each instance's media storage (AgentOS stores run media; ``agnostic_bridge.artifacts``
collects what harnesses write into it). This module serves them to people who can read the session, in a preview that
cannot reach the control plane, and keeps share links: expiring, revocable, pinned to the bytes that were shared.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_artifacts.api.router import router, share_router
from agnostic_artifacts.application.ports import MANAGE, SHARE
from agnostic_artifacts.infrastructure.tables import ArtifactsBase
from agnostic_artifacts.providers import ArtifactsProvider
from agnostic_artifacts.settings import ArtifactsSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, RouterSpec, ScopeDecl


class ArtifactsModule(BaseModule):
    name = "artifacts"
    version = "0.3.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def settings_model(self) -> type[BaseSettings] | None:
        return ArtifactsSettings

    def provide(self) -> Iterable[Provider]:
        return (ArtifactsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("artifacts",)),
            RouterSpec(router=share_router, prefix="/shares", tags=("artifacts",)),
        )

    def metadata(self) -> MetaData | None:
        return ArtifactsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl(SHARE, "Share artefacts you can read through expiring links, and revoke your links"),
            ScopeDecl(MANAGE, "See and revoke everyone's artefact share links"),
        )

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("artifact.share.created", "{actor} shared {file} with {audience}"),
            AuditActionDecl("artifact.share.revoked", "{actor} revoked the link to {file} ({audience})"),
            AuditActionDecl("artifact.share.opened", "{actor} opened the shared {file} ({audience})"),
        )
