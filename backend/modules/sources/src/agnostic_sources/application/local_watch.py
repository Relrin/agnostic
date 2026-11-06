"""Watching local folder sources: a change on disk queues a fetch, so it shows up as incoming changes.

One process watches (the one holding a short lease in the ephemeral store); the set of folders is reconciled every
little while, so new and removed sources are picked up without a restart.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from dishka import AsyncContainer
from watchfiles import awatch  # pyright: ignore[reportUnknownVariableType]

from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.ports import SourceLimits, SourceStore
from agnostic_sources.application.tasks import SourceJobs

log = get_logger(__name__)

LEASE_KEY = "sources:watch-lease"
LEASE_SECONDS = 60.0
RECONCILE_SECONDS = 30.0


class LocalWatchSupervisor:
    def __init__(self, container: AsyncContainer, settings: SourceLimits, ephemeral: EphemeralStore) -> None:
        self._container = container
        self._settings = settings
        self._ephemeral = ephemeral
        self._watchers: dict[str, tuple[asyncio.Task[None], asyncio.Event]] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="sources-watch")

    async def stop(self) -> None:
        for task, stop in self._watchers.values():
            stop.set()
            _ = task.cancel()
        self._watchers.clear()
        if self._task is not None:
            _ = self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.reconcile()
            except Exception as exc:  # noqa: BLE001  (a broken folder must not stop watching the others)
                log.warning("sources.watch_failed", error=str(exc))
            await asyncio.sleep(RECONCILE_SECONDS)

    async def reconcile(self) -> None:
        if not await self._lease():
            return
        async with self._container() as request:
            store = await request.get(SourceStore)
            wanted = {
                source.id: source.local_path or ""
                for source in await store.sources()
                if source.is_local and source.status == "active"
            }
        for source_id in [item for item in self._watchers if item not in wanted]:
            task, stop = self._watchers.pop(source_id)
            stop.set()
            _ = task.cancel()
        for source_id, root in wanted.items():
            # A watcher that stopped on its own (the folder was unmounted or removed) is started again.
            if source_id not in self._watchers or self._watchers[source_id][0].done():
                stop = asyncio.Event()
                self._watchers[source_id] = (asyncio.create_task(self._watch(source_id, root, stop)), stop)

    async def _lease(self) -> bool:
        if await self._ephemeral.set_if_absent(LEASE_KEY, b"1", ttl=LEASE_SECONDS):
            return True
        if self._watchers:
            await self._ephemeral.expire(LEASE_KEY, LEASE_SECONDS)
            return True
        return False

    async def _watch(self, source_id: str, root: str, stop: asyncio.Event) -> None:
        async for _ in awatch(root, debounce=self._settings.watch_debounce_ms, stop_event=stop, recursive=True):
            await self._queue(source_id)

    async def _queue(self, source_id: str) -> None:
        async with self._container() as request:
            _ = await (await request.get(SourceJobs)).fetch(source_id, "watch")
