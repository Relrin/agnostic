"""Names of the jobs on the ``git`` queue, and how they are queued (one at a time per source)."""

from __future__ import annotations

from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.jobs import JobQueue

QUEUE = "git"
SCAN_TASK = "sources.scan"
FETCH_TASK = "sources.fetch"
COMPUTE_TASK = "sources.compute_incoming"
PULL_TASK = "sources.pull_as_drafts"
PREPARE_TASK = "sources.prepare_outgoing"
COMMIT_TASK = "sources.commit_and_pr"
REFRESH_TASK = "sources.refresh_pr_status"
WRITE_BACK_TASK = "sources.write_back"
FETCH_ALL_TASK = "sources.fetch_all"
REFRESH_ALL_TASK = "sources.refresh_all_pr_status"
GC_TASK = "sources.gc"


def lock(source_id: str) -> str:
    return f"sources:{source_id}"


class SourceJobs:
    def __init__(self, queue: JobQueue, bus: EventBus) -> None:
        self._queue = queue
        self._bus = bus

    async def scan(self, source_id: str) -> int:
        return await self._queue.defer(SCAN_TASK, lock=lock(source_id), source_id=source_id)

    async def fetch(self, source_id: str, reason: str) -> int | None:
        """A fetch, unless one is already waiting (a burst of pushes needs only one)."""
        return await self._queue.defer_once(
            FETCH_TASK, queueing_lock=f"fetch:{source_id}", lock=lock(source_id), source_id=source_id, reason=reason
        )

    async def compute(self, source_id: str, reason: str) -> int:
        return await self._queue.defer(COMPUTE_TASK, lock=lock(source_id), source_id=source_id, reason=reason)

    async def pull(self, source_id: str, change_ids: list[str]) -> int:
        return await self._queue.defer(
            PULL_TASK, lock=lock(source_id), source_id=source_id, change_ids=list(change_ids)
        )

    async def prepare(self, source_id: str) -> int:
        return await self._queue.defer(PREPARE_TASK, lock=lock(source_id), source_id=source_id)

    async def commit(
        self,
        source_id: str,
        change_ids: list[str],
        message: str | None,
        actor_id: str | None,
        actor_name: str,
        actor_email: str | None,
    ) -> int:
        return await self._queue.defer(
            COMMIT_TASK,
            lock=lock(source_id),
            source_id=source_id,
            change_ids=list(change_ids),
            message=message,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_email=actor_email,
        )

    async def write_back(
        self,
        source_id: str,
        component_id: str,
        version: int,
        actor_id: str | None,
        actor_name: str,
        actor_email: str | None,
    ) -> int:
        """Write a published version back to the source (after a publish)."""
        return await self._queue.defer(
            WRITE_BACK_TASK,
            lock=lock(source_id),
            source_id=source_id,
            component_id=component_id,
            version=version,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_email=actor_email,
        )

    async def refresh(self, source_id: str, number: int | None) -> int | None:
        return await self._queue.defer_once(
            REFRESH_TASK,
            queueing_lock=f"refresh:{source_id}:{number}",
            lock=lock(source_id),
            source_id=source_id,
            number=number,
        )

    async def announce(self, instance_id: str, kind: str, data: dict[str, object]) -> None:
        """``sources.changed`` (a source's changes moved) or ``sources.conflicts`` (the open conflict count)."""
        payload = {**data, "instance_id": instance_id}
        await self._bus.publish(instance_channel(instance_id), RealtimeEvent(kind, payload, instance_id=instance_id))
