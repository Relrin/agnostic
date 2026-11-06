"""Listing, adding, changing and removing tool catalog entries, and what each viewer sees of them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_directory.facade import DirectoryFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError, VersionConflictError
from agnostic_kernel.ids import new_id
from agnostic_studio.facade import StudioFacade, UsedBy
from agnostic_tool_catalog.application.ports import (
    COMPONENTS_WRITE,
    LOCAL,
    READ,
    WRITE,
    EntryRepository,
    NotifyQueue,
)
from agnostic_tool_catalog.application.toolkits import Toolkits
from agnostic_tool_catalog.domain.entries import (
    LEVEL_LABELS,
    Draft,
    Entry,
    EntryStatus,
    InvalidEntryError,
    Kind,
    Level,
    Viewer,
    check_slug,
    clean_mcp,
    clean_tool_names,
    clean_toolkit,
    may_change,
    order_key,
    registry_name,
    same_tool,
    slugify,
    visible,
)

ID_PREFIX = "tce"
MAX_DISPLAY_NAME = 200
EDITABLE_FIELDS = frozenset(
    {"display_name", "description", "icon", "transport", "config", "requires_confirmation_tools", "instance_ids"}
)


@dataclass(frozen=True, slots=True)
class SameTool:
    entry_id: str
    registry_name: str
    level: Level
    level_label: str
    display_name: str


@dataclass(frozen=True, slots=True)
class EntryView:
    entry: Entry
    level_label: str
    """``Organization``, ``Team · Data`` or ``Custom``."""
    owner_group_name: str | None
    editable: bool
    same_as: tuple[SameTool, ...]


@dataclass(frozen=True, slots=True)
class Changes:
    values: dict[str, Any]
    version: int


class CatalogAccess:
    """Who the viewer is to the catalog: their groups, the groups they own, and whether they manage it."""

    def __init__(self, authorizer: Authorizer, directory: DirectoryFacade) -> None:
        self._authorizer = authorizer
        self._directory = directory

    async def viewer(self, principal: Principal) -> Viewer:
        _ = await self._authorizer.require(principal, READ)
        groups = await self._directory.groups_of(principal.id) if principal.kind == "user" else []
        owned = {group.id for group in groups if principal.id in await self._directory.owners_of(group.id)}
        return Viewer(
            user_id=principal.id,
            group_ids=frozenset(group.id for group in groups),
            owned_group_ids=frozenset(owned),
            manager=(await self._authorizer.check(principal, WRITE)).allowed,
            can_add_local=(await self._authorizer.check(principal, LOCAL)).allowed,
        )

    async def group_names(self) -> dict[str, str]:
        return {group.id: group.name for group in await self._directory.groups()}


class CatalogViews:
    """What a viewer sees of the catalog (Studio reads it too, so it depends on nothing of Studio's)."""

    def __init__(self, access: CatalogAccess, entries: EntryRepository, instances: InstancesFacade) -> None:
        self._access = access
        self._entries = entries
        self._instances = instances

    async def list(
        self,
        principal: Principal,
        *,
        kind: Kind | None = None,
        level: Level | None = None,
        instance: str | None = None,
        query: str | None = None,
    ) -> list[EntryView]:
        viewer = await self._access.viewer(principal)
        instance_id = (await self._instance(instance)).id if instance else None
        shown = [entry for entry in await self._entries.list() if visible(entry, viewer)]
        names = await self._access.group_names()
        needle = (query or "").strip().lower()
        views = [
            self._view(entry, viewer, names, shown)
            for entry in shown
            if (kind is None or entry.kind == kind)
            and (level is None or entry.level == level)
            and (instance_id is None or entry.applies_to(instance_id))
            and (not needle or needle in f"{entry.display_name} {entry.registry_name} {entry.description}".lower())
        ]
        return sorted(views, key=lambda view: order_key(view.entry))

    async def get(self, principal: Principal, entry_id: str) -> EntryView:
        viewer = await self._access.viewer(principal)
        entry = await self._entries.get(entry_id)
        if entry is None or not visible(entry, viewer):
            raise NotFoundError(f"There is no tool catalog entry {entry_id!r}.")
        shown = [other for other in await self._entries.list() if visible(other, viewer)]
        return self._view(entry, viewer, await self._access.group_names(), shown)

    async def for_instance(self, principal: Principal, instance: Instance) -> list[EntryView]:
        """The active entries the viewer may build with on this instance (what Studio's blocks show)."""
        viewer = await self._access.viewer(principal)
        shown = [
            entry
            for entry in await self._entries.list()
            if entry.status == "active" and entry.applies_to(instance.id) and visible(entry, viewer)
        ]
        names = await self._access.group_names()
        return sorted((self._view(entry, viewer, names, shown) for entry in shown), key=lambda v: order_key(v.entry))

    def _view(self, entry: Entry, viewer: Viewer, names: dict[str, str], shown: Sequence[Entry]) -> EntryView:
        group = names.get(entry.owner_group_id or "") if entry.owner_group_id else None
        return EntryView(
            entry=entry,
            level_label=level_label(entry.level, group),
            owner_group_name=group,
            editable=may_change(entry.level, entry.owner_group_id, entry.created_by, viewer)
            and (not entry.local or viewer.can_add_local),
            same_as=tuple(
                SameTool(
                    other.id,
                    other.registry_name,
                    other.level,
                    level_label(other.level, names.get(other.owner_group_id or "")),
                    other.display_name,
                )
                for other in same_tool(entry, shown)
                if other.status == "active"
            ),
        )

    async def _instance(self, ref: str) -> Instance:
        instance = await self._instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        return instance


class ToolCatalog:
    def __init__(
        self,
        access: CatalogAccess,
        views: CatalogViews,
        authorizer: Authorizer,
        entries: EntryRepository,
        toolkits: Toolkits,
        instances: InstancesFacade,
        directory: DirectoryFacade,
        studio: StudioFacade,
        audit: AuditLog,
        notify: NotifyQueue,
    ) -> None:
        self._access = access
        self._views = views
        self._authorizer = authorizer
        self._entries = entries
        self._toolkits = toolkits
        self._instances = instances
        self._directory = directory
        self._studio = studio
        self._audit = audit
        self._notify = notify

    # ------------------------------------------------------------ reading

    async def list(
        self,
        principal: Principal,
        *,
        kind: Kind | None = None,
        level: Level | None = None,
        instance: str | None = None,
        query: str | None = None,
    ) -> list[EntryView]:
        return await self._views.list(principal, kind=kind, level=level, instance=instance, query=query)

    async def get(self, principal: Principal, entry_id: str) -> EntryView:
        return await self._views.get(principal, entry_id)

    async def for_instance(self, principal: Principal, instance: Instance) -> list[EntryView]:
        return await self._views.for_instance(principal, instance)

    # ------------------------------------------------------------ changing

    async def create(self, principal: Principal, draft: Draft) -> EntryView:
        viewer = await self._access.viewer(principal)
        group_slug = await self._owner(draft, viewer)
        await self._may_reach(principal, viewer, draft.level, draft.instance_ids)
        entry_id = new_id(ID_PREFIX)
        now = utcnow()
        try:
            slug = check_slug(draft.slug)
            name = registry_name(draft.level, slug, group_slug=group_slug, entry_id=entry_id)
            entry = Entry(
                id=entry_id,
                slug=slug,
                registry_name=name,
                level=draft.level,
                owner_group_id=draft.owner_group_id,
                display_name=_display_name(draft.display_name),
                description=draft.description.strip(),
                icon=(draft.icon or "").strip() or None,
                kind=draft.kind,
                transport=draft.transport if draft.kind == "mcp" else None,
                toolkit_key=draft.toolkit_key if draft.kind == "toolkit" else None,
                config={},
                requires_confirmation_tools=clean_tool_names(
                    "Tools that need approval", list(draft.requires_confirmation_tools)
                ),
                instance_ids=await self._instance_ids(draft.instance_ids),
                status="active",
                version=1,
                created_by=principal.id,
                created_at=now,
                updated_at=now,
            )
            entry = self._clean(entry, draft.config)
        except InvalidEntryError as exc:
            raise ValidationFailedError(str(exc)) from exc
        await self._may_add_local(principal, entry)
        if await self._entries.by_registry_name(entry.registry_name) is not None:
            raise ConflictError(f"{entry.registry_name} is taken; pick another name.")
        await self._entries.add(entry)
        await self._record(principal, "tool_catalog.create", entry, diff={"after": _public(entry)})
        await self._entries.commit()
        await self._notify.notify(list(entry.instance_ids))
        return await self.get(principal, entry.id)

    async def update(self, principal: Principal, entry_id: str, changes: Changes) -> EntryView:
        viewer = await self._access.viewer(principal)
        before = await self._changeable(entry_id, viewer)
        unknown = sorted(set(changes.values) - EDITABLE_FIELDS)
        if unknown:
            raise ValidationFailedError(
                f"{', '.join(unknown)} can't change: the runtime knows the tool by its name, level and kind. "
                "Add a new entry instead."
            )
        if changes.version != before.version:
            raise VersionConflictError("Someone else changed this entry; reload and try again.")
        values = changes.values
        try:
            entry = replace(
                before,
                display_name=_display_name(values.get("display_name", before.display_name)),
                description=str(values.get("description", before.description) or "").strip(),
                icon=(str(values.get("icon") or "").strip() or None) if "icon" in values else before.icon,
                transport=values.get("transport", before.transport) if before.kind == "mcp" else None,
                requires_confirmation_tools=clean_tool_names(
                    "Tools that need approval",
                    list(values.get("requires_confirmation_tools", before.requires_confirmation_tools)),
                ),
                instance_ids=(
                    await self._instance_ids(values["instance_ids"])
                    if "instance_ids" in values
                    else before.instance_ids
                ),
                version=before.version + 1,
                updated_at=utcnow(),
            )
            if "config" in values or entry.transport != before.transport:
                # A rename or a new description leaves the settings as they were checked when saved.
                entry = self._clean(entry, values.get("config", _editable_config(before)))
        except InvalidEntryError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if entry.instance_ids != before.instance_ids:
            await self._may_reach(principal, viewer, entry.level, entry.instance_ids)
        await self._may_add_local(principal, entry)
        if not await self._entries.save(entry, expected_version=before.version):
            raise VersionConflictError("Someone else changed this entry; reload and try again.")
        await self._record(
            principal, "tool_catalog.update", entry, diff={"before": _public(before), "after": _public(entry)}
        )
        await self._entries.commit()
        await self._notify.notify(_affected(before, entry))
        return await self.get(principal, entry.id)

    async def set_status(self, principal: Principal, entry_id: str, status: EntryStatus) -> EntryView:
        viewer = await self._access.viewer(principal)
        before = await self._changeable(entry_id, viewer)
        if before.status == status:
            return await self.get(principal, entry_id)
        entry = replace(before, status=status, version=before.version + 1, updated_at=utcnow())
        if status == "active":
            await self._may_add_local(principal, entry)
        if not await self._entries.save(entry, expected_version=before.version):
            raise VersionConflictError("Someone else changed this entry; reload and try again.")
        action = "tool_catalog.enable" if status == "active" else "tool_catalog.disable"
        await self._record(principal, action, entry)
        await self._entries.commit()
        await self._notify.notify(list(entry.instance_ids))
        return await self.get(principal, entry_id)

    async def delete(self, principal: Principal, entry_id: str, *, force: bool = False) -> None:
        viewer = await self._access.viewer(principal)
        entry = await self._changeable(entry_id, viewer)
        if not force:
            users = await self.used_by(entry)
            if users:
                names = ", ".join(sorted({f"{use.component_name} ({where})" for where, use in users})[:10])
                raise ConflictError(
                    f"{entry.display_name} is used by {names}. Remove it from them first, or delete it anyway.",
                    extra={"used_by": [_used(where, use) for where, use in users]},
                )
        await self._entries.delete(entry.id)
        await self._record(principal, "tool_catalog.delete", entry, diff={"before": _public(entry)})
        await self._entries.commit()
        await self._notify.notify(list(entry.instance_ids))

    async def used_by(self, entry: Entry) -> list[tuple[str, UsedBy]]:
        """Components on the instances the entry applies to that use it (instance name, component)."""
        found: list[tuple[str, UsedBy]] = []
        for instance in await self._instances.list():
            if entry.applies_to(instance.id):
                found.extend(
                    (instance.display_name, use)
                    for use in await self._studio.used_by(instance, "tool", entry.registry_name)
                )
        return found

    # ------------------------------------------------------------ helpers

    def _clean(self, entry: Entry, config: dict[str, Any]) -> Entry:
        if entry.kind == "mcp":
            cleaned = clean_mcp(entry.transport, config, name=entry.registry_name)
            return replace(entry, config=cleaned, local=entry.transport == "stdio")
        toolkit = self._toolkits.info(entry.toolkit_key or "")
        return replace(entry, config=clean_toolkit(toolkit, config), local=bool(toolkit and toolkit.local))

    async def _owner(self, draft: Draft, viewer: Viewer) -> str | None:
        """Check who may add at this level; returns the owning group's slug for team entries."""
        if draft.level not in LEVEL_LABELS:
            raise ValidationFailedError("Pick a level: org, team or custom.")
        if draft.kind not in {"mcp", "toolkit"}:
            raise ValidationFailedError("Pick a kind: mcp or toolkit.")
        group = await self._directory.group(draft.owner_group_id) if draft.owner_group_id else None
        if draft.owner_group_id and group is None:
            raise ValidationFailedError(f"There is no group {draft.owner_group_id!r}.")
        if draft.level == "team" and group is None:
            raise ValidationFailedError("A team entry belongs to a group: pick one.")
        if draft.level == "org" and draft.owner_group_id:
            raise ValidationFailedError("An organization entry doesn't belong to a group.")
        if draft.level == "custom" and group is not None and not (viewer.manager or group.id in viewer.group_ids):
            raise ValidationFailedError("A custom entry can only belong to a group you are in.")
        if not may_change(draft.level, draft.owner_group_id, viewer.user_id, viewer):
            who = (
                "org owners and administrators"
                if draft.level == "org"
                else f"the owners of {group.name if group else 'the group'}"
            )
            raise ValidationFailedError(f"Only {who} can add {LEVEL_LABELS[draft.level].lower()} entries.")
        return slugify(group.name) if draft.level == "team" and group is not None else None

    async def _changeable(self, entry_id: str, viewer: Viewer) -> Entry:
        entry = await self._entries.get(entry_id)
        if entry is None or not visible(entry, viewer):
            raise NotFoundError(f"There is no tool catalog entry {entry_id!r}.")
        if not may_change(entry.level, entry.owner_group_id, entry.created_by, viewer):
            raise ValidationFailedError(f"You can't change {entry.display_name}; ask whoever set it up.")
        return entry

    async def _may_add_local(self, principal: Principal, entry: Entry) -> None:
        if entry.local:
            _ = await self._authorizer.require(principal, LOCAL)

    async def _may_reach(
        self, principal: Principal, viewer: Viewer, level: Level, instance_refs: Sequence[str]
    ) -> None:
        """Which runtimes an entry may go to.

        Catalog managers choose freely. Anyone else only reaches instances they may build on: an entry makes a
        runtime connect somewhere with credentials it names.
        """
        if level == "custom":
            await self._may_build_on(principal, instance_refs)
            return
        if viewer.manager:
            return
        if not instance_refs:
            raise ValidationFailedError(
                "Pick the instances this tool goes to: only catalog managers offer tools on every instance."
            )
        for ref in instance_refs:
            instance = await self._instance(ref)
            _ = await self._authorizer.require(principal, COMPONENTS_WRITE, instance_id=instance.id)

    async def _may_build_on(self, principal: Principal, instance_refs: Sequence[str]) -> None:
        if len(instance_refs) != 1:
            raise ValidationFailedError("A custom entry is made for one instance: the one its component is on.")
        instance = await self._instance(instance_refs[0])
        _ = await self._authorizer.require(principal, COMPONENTS_WRITE, instance_id=instance.id)

    async def _instance(self, ref: str) -> Instance:
        instance = await self._instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        return instance

    async def _instance_ids(self, refs: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys([(await self._instance(ref)).id for ref in refs]))

    async def _record(
        self, principal: Principal, action: str, entry: Entry, *, diff: dict[str, Any] | None = None
    ) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="tool_catalog_entry",
                resource_id=entry.id,
                resource_display=entry.display_name,
                fields={"entry": entry.display_name, "level": LEVEL_LABELS[entry.level], "name": entry.registry_name},
                diff=diff,
            )
        )


def level_label(level: Level, group_name: str | None) -> str:
    if level == "team":
        return f"Team · {group_name}" if group_name else "Team"
    return LEVEL_LABELS[level]


def _display_name(value: object) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > MAX_DISPLAY_NAME:
        raise InvalidEntryError(f"Give it a name of 1 to {MAX_DISPLAY_NAME} characters.")
    return name


def _editable_config(entry: Entry) -> dict[str, Any]:
    if entry.kind == "toolkit":
        return {"params": dict(entry.config.get("params") or {})}
    return {key: value for key, value in entry.config.items() if key != "transport"}


def _public(entry: Entry) -> dict[str, Any]:
    """An entry for the audit trail (no secrets exist to hide: credentials are env var names)."""
    return {
        "registry_name": entry.registry_name,
        "display_name": entry.display_name,
        "level": entry.level,
        "kind": entry.kind,
        "transport": entry.transport,
        "toolkit": entry.toolkit_key,
        "config": entry.config,
        "instances": list(entry.instance_ids),
        "status": entry.status,
    }


def _used(where: str, use: UsedBy) -> dict[str, str]:
    return {"instance": where, "component_id": use.component_id, "kind": use.component_kind, "name": use.component_name}


def _affected(before: Entry, after: Entry) -> list[str]:
    """Instances whose bridge should pull again; empty means every instance."""
    if not before.instance_ids or not after.instance_ids:
        return []
    return sorted(set(before.instance_ids) | set(after.instance_ids))
