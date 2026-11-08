"""Module declaration: code sources, the repositories and local folders Studio syncs with.

Pulled changes arrive as drafts, publishes write back as pull requests (or commits), and edits made in both places
merge field by field. Nothing moves until someone pulls or commits.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from dishka import AsyncContainer, Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import utcnow
from agnostic_kernel.diagnostics import StatusItem
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import (
    AuditActionDecl,
    BaseModule,
    EventHandlerSpec,
    JobSpec,
    RouterSpec,
    ScopeDecl,
    SealedColumn,
)
from agnostic_sources import jobs
from agnostic_sources.api.hooks import hooks_router
from agnostic_sources.api.router import org_router, router
from agnostic_sources.application import tasks
from agnostic_sources.application.local_watch import LocalWatchSupervisor
from agnostic_sources.application.ports import GitRepo, SourceLimits
from agnostic_sources.infrastructure.status import webhook_status
from agnostic_sources.infrastructure.tables import SourcesBase
from agnostic_sources.providers import SourcesProvider
from agnostic_sources.settings import SourcesSettings
from agnostic_studio.facade import PUBLISHED_EVENT

log = get_logger(__name__)


class SourcesModule(BaseModule):
    name = "sources"
    version = "0.4.0"
    depends_on = ("access", "audit", "instances", "gateway", "studio")

    def __init__(self) -> None:
        self._watch: LocalWatchSupervisor | None = None

    def settings_model(self) -> type[BaseSettings] | None:
        return SourcesSettings

    def provide(self) -> Iterable[Provider]:
        return (SourcesProvider(),)

    def sealed_columns(self) -> Iterable[SealedColumn]:
        return (
            SealedColumn("src_connections", "config_enc"),
            SealedColumn("src_sources", "webhook_secret_enc"),
        )

    def routers(self) -> Iterable[RouterSpec]:
        return (
            RouterSpec(router=router, prefix="/instances", tags=("sources",)),
            RouterSpec(router=org_router, tags=("sources",)),
            RouterSpec(router=hooks_router, prefix="/hooks", tags=("hooks",), root=True),
        )

    def metadata(self) -> MetaData | None:
        return SourcesBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def scopes(self) -> Iterable[ScopeDecl]:
        return (
            ScopeDecl("studio:sources:read", "See code source connections and webhook deliveries"),
            ScopeDecl("studio:sources:write", "Connect and configure code sources"),
            ScopeDecl("studio:sources:delete", "Disconnect code sources"),
        )

    def jobs(self) -> Iterable[JobSpec]:
        settings = SourcesSettings()
        specs = [
            JobSpec(name=tasks.SCAN_TASK, func=jobs.scan, queue=tasks.QUEUE),
            JobSpec(name=tasks.FETCH_TASK, func=jobs.fetch, queue=tasks.QUEUE),
            JobSpec(name=tasks.COMPUTE_TASK, func=jobs.compute_incoming, queue=tasks.QUEUE),
            JobSpec(name=tasks.PULL_TASK, func=jobs.pull_as_drafts, queue=tasks.QUEUE),
            JobSpec(name=tasks.PREPARE_TASK, func=jobs.prepare_outgoing, queue=tasks.QUEUE),
            JobSpec(name=tasks.COMMIT_TASK, func=jobs.commit_and_pr, queue=tasks.QUEUE),
            JobSpec(name=tasks.REFRESH_TASK, func=jobs.refresh_pr_status, queue=tasks.QUEUE),
            JobSpec(name=tasks.WRITE_BACK_TASK, func=jobs.write_back, queue=tasks.QUEUE),
        ]
        periodic = (
            (tasks.FETCH_ALL_TASK, jobs.fetch_all, settings.fetch_cron),
            (tasks.REFRESH_ALL_TASK, jobs.refresh_all, settings.pull_request_cron),
            (tasks.GC_TASK, jobs.gc, settings.gc_cron),
        )
        specs.extend(
            JobSpec(name=name, func=func, queue=tasks.QUEUE, periodic=cron) for name, func, cron in periodic if cron
        )
        return specs

    def event_handlers(self) -> Iterable[EventHandlerSpec]:
        return (EventHandlerSpec(PUBLISHED_EVENT, jobs.on_published),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("sources.connection.create", "{actor} connected {connection} ({provider})"),
            AuditActionDecl("sources.connection.update", "{actor} changed the connection {connection} ({status})"),
            AuditActionDecl("sources.connection.delete", "{actor} removed the connection {connection}"),
            AuditActionDecl("sources.source.create", "{actor} connected {source} · {branch} to {instance}"),
            AuditActionDecl("sources.source.update", "{actor} changed the source {source} · {branch} on {instance}"),
            AuditActionDecl("sources.source.delete", "{actor} disconnected {source} · {branch} from {instance}"),
            AuditActionDecl("sources.fetch", "{actor} fetched {source} · {branch}"),
            AuditActionDecl("sources.pull", "{actor} pulled {count} change(s) from {source} as drafts: {components}"),
            AuditActionDecl("sources.commit", "{actor} committed {count} change(s): {message} ({where})"),
            AuditActionDecl("sources.pr.open", "{actor} opened pull request #{number} from {branch}"),
            AuditActionDecl("sources.pr.merged", "Pull request #{number} ({branch}) was merged"),
            AuditActionDecl("sources.pr.closed", "Pull request #{number} ({branch}) was closed without merging"),
            AuditActionDecl("sources.conflict.resolve", "{actor} resolved {field} in {path}: {resolution}"),
        )

    async def on_startup(self, container: AsyncContainer) -> None:
        version = await (await container.get(GitRepo)).version()
        if version is None:
            log.warning("sources.git_missing", detail="git sources can't fetch until git is installed")
        settings = await container.get(SourcesSettings)
        if settings.watch_local and settings.local_roots:
            limits = await container.get(SourceLimits)
            self._watch = LocalWatchSupervisor(container, limits, await container.get(EphemeralStore))
            self._watch.start()

    async def on_shutdown(self, container: AsyncContainer) -> None:  # noqa: ARG002
        if self._watch is not None:
            await self._watch.stop()
            self._watch = None

    async def system_status(self, container: AsyncContainer) -> Sequence[StatusItem]:
        return await webhook_status(await container.get(AsyncSession), utcnow())
