"""Periodic work: fetch sources without webhooks, check open pull requests, and keep mirrors within their quotas."""

from __future__ import annotations

from dataclasses import replace

from agnostic_kernel.logging import get_logger
from agnostic_sources.application.ports import GitRepo, SourceLimits, SourceStore
from agnostic_sources.application.tasks import SourceJobs

log = get_logger(__name__)


class Housekeeping:
    def __init__(self, store: SourceStore, git: GitRepo, jobs: SourceJobs, settings: SourceLimits) -> None:
        self._store = store
        self._git = git
        self._jobs = jobs
        self._settings = settings

    async def fetch_all(self) -> int:
        """Fetch active sources that no webhook keeps up to date (and local folders when nothing watches them)."""
        queued = 0
        for source in await self._store.sources():
            if source.status != "active" or (source.webhook_id and not source.is_local):
                continue
            if source.is_local and self._settings.watch_local:
                continue
            _ = await self._jobs.fetch(source.id, "periodic")
            queued += 1
        return queued

    async def refresh_all(self) -> int:
        sources = {pull.source_id for pull in await self._store.pull_requests(open_only=True)}
        for source_id in sources:
            _ = await self._jobs.refresh(source_id, None)
        return len(sources)

    async def gc(self) -> None:
        known = {source.id for source in await self._store.sources() if not source.is_local}
        for mirror in await self._git.mirrors():
            if mirror not in known:
                await self._git.remove(mirror)
        total = 0
        for source in await self._store.sources():
            if source.is_local:
                continue
            await self._git.gc(source.id)
            size = await self._git.size(source.id)
            total += size
            if size > self._settings.mirror_quota_mb * 1024 * 1024 and source.status == "active":
                _ = await self._store.save_source(
                    replace(source, status="over_quota", status_detail="The mirror is over its quota after gc.")
                )
        if total > self._settings.total_quota_mb * 1024 * 1024:
            log.warning("sources.mirrors_over_total_quota", total_mb=total // (1024 * 1024))
        pruned = await self._store.prune_deliveries(self._settings.delivery_retention_days)
        await self._store.commit()
        log.info("sources.gc", mirrors=len(known), total_mb=total // (1024 * 1024), deliveries_pruned=pruned)
