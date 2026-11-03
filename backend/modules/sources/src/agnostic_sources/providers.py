"""Dependency wiring of the sources module."""

from __future__ import annotations

from collections.abc import AsyncIterator

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_sources.application.access import SourcesAccess
from agnostic_sources.application.connections import Connections
from agnostic_sources.application.files import SourceFiles
from agnostic_sources.application.housekeeping import Housekeeping
from agnostic_sources.application.outgoing import (
    Committer,
    OnPublished,
    OutgoingPreparer,
    PullRequestTracker,
    SourcePublishHold,
)
from agnostic_sources.application.ports import (
    Folders,
    GitRepo,
    ProviderClients,
    SourceLimits,
    SourceStore,
    WebhookUrls,
)
from agnostic_sources.application.sources import Sources
from agnostic_sources.application.sync import ConflictResolver, Fetcher, IncomingComputer, Puller
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.application.views import SourceViews
from agnostic_sources.application.webhooks import WebhookIntake
from agnostic_sources.infrastructure.git_cli import GitCli
from agnostic_sources.infrastructure.hooks import PublicWebhookUrls
from agnostic_sources.infrastructure.http import SourcesHttp
from agnostic_sources.infrastructure.local_folders import LocalFolders
from agnostic_sources.infrastructure.providers import HttpProviderClients
from agnostic_sources.infrastructure.providers.github import GitHubAppTokens
from agnostic_sources.infrastructure.repository import SqlSourceStore
from agnostic_sources.settings import SourcesSettings
from agnostic_studio.facade import PublishHold


class SourcesProvider(Provider):
    scope = Scope.REQUEST

    access = provide(SourcesAccess)
    jobs = provide(SourceJobs)
    files = provide(SourceFiles)
    connections = provide(Connections)
    sources = provide(Sources)
    views = provide(SourceViews)
    fetcher = provide(Fetcher)
    incoming = provide(IncomingComputer)
    puller = provide(Puller)
    conflicts = provide(ConflictResolver)
    preparer = provide(OutgoingPreparer)
    committer = provide(Committer)
    tracker = provide(PullRequestTracker)
    on_published = provide(OnPublished)
    intake = provide(WebhookIntake)
    housekeeping = provide(Housekeeping)
    publish_hold = provide(SourcePublishHold, provides=PublishHold, override=True)

    @provide
    def store(self, session: AsyncSession, box: SecretBox) -> SourceStore:
        return SqlSourceStore(session, box)

    @provide(scope=Scope.APP)
    def limits(self, settings: SourcesSettings) -> SourceLimits:
        return SourceLimits(
            max_changed_files=settings.max_changed_files,
            max_file_bytes=settings.max_file_bytes,
            allow_file_remotes=settings.allow_file_remotes,
            mirror_quota_mb=settings.mirror_quota_mb,
            total_quota_mb=settings.total_quota_mb,
            delivery_retention_days=settings.delivery_retention_days,
            committer_name=settings.committer_name,
            committer_email=settings.committer_email,
            github_app_slug=settings.github_app_slug,
            github_web_url=settings.github_web_url,
            watch_local=settings.watch_local,
            watch_debounce_ms=settings.watch_debounce_ms,
        )

    @provide(scope=Scope.APP)
    def git(self, settings: SourcesSettings) -> GitRepo:
        return GitCli(settings)

    @provide(scope=Scope.APP)
    def folders(self, settings: SourcesSettings) -> Folders:
        return LocalFolders(settings)

    @provide(scope=Scope.APP)
    async def http(self, settings: SourcesSettings) -> AsyncIterator[SourcesHttp]:
        client = SourcesHttp(timeout=settings.provider_timeout_seconds)
        yield client
        await client.aclose()

    @provide(scope=Scope.APP)
    def tokens(self, http: SourcesHttp, ephemeral: EphemeralStore, box: SecretBox) -> GitHubAppTokens:
        return GitHubAppTokens(http.client, ephemeral, box)

    @provide(scope=Scope.APP)
    def clients(self, http: SourcesHttp, settings: SourcesSettings, tokens: GitHubAppTokens) -> ProviderClients:
        return HttpProviderClients(http, settings, tokens)

    hooks = provide(PublicWebhookUrls, provides=WebhookUrls, scope=Scope.APP)
