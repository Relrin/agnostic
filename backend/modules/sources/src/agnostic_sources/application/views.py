"""What the Sources page and the editors' source bar show."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import NotFoundError
from agnostic_sources.application.access import COMPONENTS_READ, COMPONENTS_WRITE, SOURCES_READ, SourcesAccess
from agnostic_sources.application.ports import SourceStore
from agnostic_sources.domain.model import (
    Change,
    Conflict,
    Connection,
    Delivery,
    FileBinding,
    PullRequest,
    Source,
)
from agnostic_studio.facade import HoldCheck, PublishHold, StudioFacade


@dataclass(frozen=True, slots=True)
class SourceCard:
    source: Source
    connection: Connection | None
    incoming: int
    outgoing: int
    conflicts: int
    open_pull_requests: int


@dataclass(frozen=True, slots=True)
class ChangesView:
    source: Source
    incoming: list[Change]
    outgoing: list[Change]
    conflicts: list[Conflict]
    pull_requests: list[PullRequest]


@dataclass(frozen=True, slots=True)
class ComponentSource:
    source: Source | None = None
    binding: FileBinding | None = None
    incoming: list[Change] = field(default_factory=list[Change])
    outgoing: list[Change] = field(default_factory=list[Change])
    conflicts: list[Conflict] = field(default_factory=list[Conflict])
    pull_request: PullRequest | None = None
    uncommitted: str | None = None
    """What Studio changed since the repository's version (``mode changed``); ``None`` when in sync."""
    uncommitted_version: int | None = None
    marks: dict[str, str] = field(default_factory=dict[str, str])
    marks_version: int | None = None
    """The draft whose code the incoming line marks are for."""
    others: list[Source] = field(default_factory=list[Source])
    hold: HoldCheck = field(default_factory=HoldCheck)


class SourceViews:
    def __init__(self, store: SourceStore, access: SourcesAccess, studio: StudioFacade, hold: PublishHold) -> None:
        self._store = store
        self._access = access
        self._studio = studio
        self._hold = hold

    async def cards(self, principal: Principal, ref: str) -> tuple[Instance, list[SourceCard]]:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        return instance, [await self._card(source) for source in await self._store.sources(instance.id)]

    async def card(self, principal: Principal, ref: str, source_id: str) -> SourceCard:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        return await self._card(self._access.owned(await self._store.source(source_id), instance))

    async def _card(self, source: Source) -> SourceCard:
        connection = await self._store.connection(source.connection_id) if source.connection_id else None
        incoming = [
            change
            for change in await self._store.changes(source.id, "incoming", ["pending"])
            if change.outcome.get("action") != "removed"
        ]
        outgoing = await self._store.changes(source.id, "outgoing", ["pending", "committing"])
        return SourceCard(
            source=source,
            connection=connection,
            incoming=len(incoming),
            outgoing=len(outgoing),
            conflicts=len(await self._store.conflicts(source.id)),
            open_pull_requests=len(await self._store.pull_requests(source.id, open_only=True)),
        )

    async def changes(self, principal: Principal, ref: str, source_id: str) -> ChangesView:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        source = self._access.owned(await self._store.source(source_id), instance)
        return ChangesView(
            source=source,
            incoming=await self._store.changes(source.id, "incoming", ["pending"]),
            outgoing=await self._store.changes(source.id, "outgoing", ["pending", "committing"]),
            conflicts=await self._store.conflicts(source.id),
            pull_requests=(await self._store.pull_requests(source.id))[:10],
        )

    async def change(self, principal: Principal, ref: str, source_id: str, change_id: str) -> tuple[Source, Change]:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        source = self._access.owned(await self._store.source(source_id), instance)
        change = await self._store.change(change_id)
        if change is None or change.source_id != source.id:
            raise NotFoundError("There is no such change on this source.")
        return source, change

    async def include(self, principal: Principal, ref: str, source_id: str, change_id: str, included: bool) -> Change:
        instance = await self._access.instance(principal, ref, COMPONENTS_WRITE)
        source = self._access.owned(await self._store.source(source_id), instance)
        change = await self._store.change(change_id)
        if change is None or change.source_id != source.id:
            raise NotFoundError("There is no such change on this source.")
        updated = replace(change, included=included)
        await self._store.save_change(updated)
        await self._store.commit()
        return updated

    async def conflict_count(self, principal: Principal, ref: str) -> tuple[Instance, int]:
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        return instance, await self._store.open_conflict_count(instance.id)

    async def deliveries(self, principal: Principal, ref: str, source_id: str) -> list[Delivery]:
        instance = await self._access.instance(principal, ref, SOURCES_READ)
        source = self._access.owned(await self._store.source(source_id), instance)
        return await self._store.deliveries(source.id)

    async def component(self, principal: Principal, ref: str, component_id: str) -> ComponentSource:
        """The editor's source bar: where the component is synced, what's incoming, uncommitted and in review."""
        instance = await self._access.instance(principal, ref, COMPONENTS_READ)
        bound = await self._store.bindings_for_component(instance.id, component_id)
        if not bound:
            return ComponentSource()
        source, binding = bound[0]
        incoming = [
            change
            for change in await self._store.changes(source.id, "incoming", ["pending"])
            if change.component_id == component_id and change.outcome.get("action") != "removed"
        ]
        outgoing = [
            change
            for change in await self._store.changes(source.id, "outgoing", ["pending", "committing"])
            if change.component_id == component_id
        ]
        conflicts = [item for item in await self._store.conflicts(source.id) if item.component_id == component_id]
        pull_request = next(
            (
                pull
                for pull in await self._store.pull_requests(source.id, open_only=True)
                if any(item.get("component_id") == component_id for item in pull.components)
            ),
            None,
        )
        uncommitted: str | None = None
        uncommitted_version: int | None = None
        state = await self._studio.component(principal, instance, component_id)
        latest = state.latest_version if state is not None else None
        synced = binding.synced_config
        if latest is not None and synced is not None and latest >= (binding.last_synced_version or 0):
            snap = await self._studio.snapshot(principal, instance, component_id, latest)
            if snap.config != synced:
                uncommitted = self._studio.summarize(synced, snap.config)
                uncommitted_version = latest
        pulled = [
            change
            for change in await self._store.changes(source.id, "incoming", ["pulled"])
            if change.component_id == component_id and change.result_version is not None
        ]
        newest = max(pulled, key=lambda change: change.result_version or 0, default=None)
        hold = (
            await self._hold.check(instance.id, component_id, state.draft_version)
            if state is not None and state.draft_version
            else HoldCheck()
        )
        return ComponentSource(
            source=source,
            binding=binding,
            incoming=incoming,
            outgoing=outgoing,
            conflicts=conflicts,
            pull_request=pull_request,
            uncommitted=uncommitted,
            uncommitted_version=uncommitted_version,
            marks=newest.incoming_marks if newest else {},
            marks_version=newest.result_version if newest else None,
            others=[item for item, _ in bound[1:]],
            hold=hold,
        )
