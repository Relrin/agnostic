"""The registry as Studio shows it, and the reverse index of which components use each entry."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, cast

from pydantic import ValidationError

from agnostic_agentos_client import AgentOSError
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_spec.v3_1 import iter_refs, parse
from agnostic_studio.application.access import (
    BRIDGE_INTROSPECT,
    BRIDGE_SOURCE,
    REGISTRY_SCOPE,
    StudioAccess,
    page_items,
)
from agnostic_studio.application.ports import StudioStore, ToolCatalogLookup
from agnostic_studio.domain.model import FAMILY, Kind
from agnostic_studio.domain.registry import (
    ENTRY_TYPES,
    EntryType,
    RegistryEntry,
    Source,
    catalog_placeholder,
    normalize,
    with_catalog,
)
from agnostic_studio.domain.usage import IndexEntry, Use, UsedBy, index

SOURCE_TTL = 300.0
INDEX_TTL = 600.0
EDITABLE: tuple[Kind, ...] = ("agent", "team", "workflow")
# AgentOS describes code-defined agents and teams with their model, tools and members; a workflow only by its steps.
DESCRIBED: tuple[Kind, ...] = ("agent", "team")


@dataclass(frozen=True, slots=True)
class Catalog:
    entries: list[RegistryEntry]
    used_by: dict[tuple[str, str], list[UsedBy]]
    bridge: bool
    """The bridge answered for sources: declared/discovered status and approval flags are exact."""

    def counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for entry in self.entries:
            found[entry.type] = found.get(entry.type, 0) + 1
        return found

    def of(self, entry_type: str, name: str) -> RegistryEntry | None:
        return next((entry for entry in self.entries if entry.type == entry_type and entry.name == name), None)

    def names(self) -> set[tuple[str, str]]:
        return {(entry.type, entry.name) for entry in self.entries} | {
            ("memory_manager", entry.id) for entry in self.entries if entry.type == "memory_manager" and entry.id
        }


class RegistryCatalog:
    def __init__(self, access: StudioAccess, store: StudioStore, tools: ToolCatalogLookup) -> None:
        self._access = access
        self._store = store
        self._tools = tools

    async def entries(self, principal: Principal, instance: Instance) -> list[RegistryEntry]:
        raw = await self._access.pages(principal, instance, "/registry")
        bridge = BRIDGE_SOURCE in await self._access.bridge(instance)
        entries: list[RegistryEntry] = []
        for item in raw:
            source = (
                await self.source(instance, str(item.get("type")), str(item.get("name")))
                if bridge and item.get("type") == "tool"
                else None
            )
            entries.append(normalize(item, source))
        entries = await self._with_catalog(principal, instance, entries)
        return sorted(
            entries, key=lambda entry: (ENTRY_TYPES.index(entry.type) if entry.type in ENTRY_TYPES else 99, entry.name)
        )

    async def _with_catalog(
        self, principal: Principal, instance: Instance, entries: list[RegistryEntry]
    ) -> list[RegistryEntry]:
        """Mark the tools that come from the tool catalog, and list the ones the runtime hasn't loaded yet."""
        offered = {tool.registry_name: tool for tool in await self._tools.for_instance(principal, instance)}
        if not offered:
            return entries
        marked: list[RegistryEntry] = []
        for entry in entries:
            tool = offered.pop(entry.name, None) if entry.type == "tool" else None
            if tool is not None and tool.info.state == "not_on_instance":
                # The runtime lists it, so it has it, whatever an older (or absent) bridge report says.
                tool = replace(tool, info=replace(tool.info, state="connected"))
            marked.append(with_catalog(entry, tool.info) if tool is not None else entry)
        marked.extend(catalog_placeholder(tool.registry_name, tool.description, tool.info) for tool in offered.values())
        return marked

    async def catalog(self, principal: Principal, ref: str) -> tuple[Instance, Catalog]:
        instance = await self._access.instance(principal, ref, REGISTRY_SCOPE)
        entries = await self.entries(principal, instance)
        used_by = await UsedByIndex(self._access, self._store).ensure(instance)
        return instance, Catalog(entries, used_by, BRIDGE_SOURCE in await self._access.bridge(instance))

    async def entry(
        self, principal: Principal, ref: str, entry_type: str, name: str
    ) -> tuple[Instance, RegistryEntry, list[UsedBy]]:
        instance, catalog = await self.catalog(principal, ref)
        found = catalog.of(entry_type, name)
        if found is None:
            raise NotFoundError(f"There is no {entry_type} {name!r} in the registry of {instance.display_name}.")
        if found.source is None and BRIDGE_SOURCE in await self._access.bridge(instance):
            source = await self.source(instance, entry_type, name)
            if source is not None:
                raw: dict[str, Any] = {
                    "type": found.type,
                    "name": found.name,
                    "id": found.id,
                    "description": found.description,
                    "metadata": found.metadata,
                }
                found = normalize(raw, source)
        return (
            instance,
            found,
            catalog.used_by.get((found.type, found.name), [])
            + (
                catalog.used_by.get(("memory_manager", found.id), [])
                if found.type == "memory_manager" and found.id
                else []
            ),
        )

    async def refresh(self, principal: Principal, ref: str) -> Instance:
        """Drop every cached view of the registry, then rebuild the used-by index."""
        instance = await self._access.instance(principal, ref, REGISTRY_SCOPE)
        await self._access.gateway.invalidate(instance)
        await self._access.forget(f"studio:bridge:{instance.id}")
        await self._access.forget(f"studio:indexed:{instance.id}")
        await UsedByIndex(self._access, self._store).rebuild(instance)
        return instance

    async def source(self, instance: Instance, entry_type: str, name: str) -> Source | None:
        key = f"studio:source:{instance.id}:{entry_type}:{name}"
        cached = await self._access.cached(key)
        if cached is not None:
            return Source(**cast("dict[str, Any]", cached)) if cached else None
        try:
            body = await self._access.system_json(instance, f"/agnostic/v1/registry/{entry_type}/{name}/source")
        except AgentOSError:
            await self._access.cache(key, {}, SOURCE_TTL)
            return None
        data = cast("dict[str, Any]", body) if isinstance(body, dict) else {}
        source = Source(
            module=data.get("module"),
            file=data.get("file"),
            line=data.get("line"),
            declared=bool(data.get("declared", True)),
            requires_confirmation=bool(data.get("requires_confirmation")),
            approval_type=data.get("approval_type"),
        )
        await self._access.cache(
            key,
            {
                "module": source.module,
                "file": source.file,
                "line": source.line,
                "declared": source.declared,
                "requires_confirmation": source.requires_confirmation,
                "approval_type": source.approval_type,
            },
            SOURCE_TTL,
        )
        return source


class UsedByIndex:
    """Scans every stored config (drafts included) and every component defined in code, as the control plane."""

    def __init__(self, access: StudioAccess, store: StudioStore) -> None:
        self._access = access
        self._store = store

    async def ensure(self, instance: Instance) -> dict[tuple[str, str], list[UsedBy]]:
        if await self._access.cached(f"studio:indexed:{instance.id}") is None:
            entries = await self.rebuild(instance)
        else:
            entries = await self._store.index(instance.id)
        return {(entry.entry_type, entry.name): entry.used_by for entry in entries}

    async def rebuild(self, instance: Instance) -> list[IndexEntry]:
        uses = [*await self._stored(instance), *await self._code(instance)]
        now = utcnow()
        entries = [
            IndexEntry(entry_type=entry_type, name=name, used_by=used_by, indexed_at=now)
            for (entry_type, name), used_by in sorted(index(uses).items())
        ]
        digest = hashlib.sha256(
            "\n".join(
                sorted(f"{use.entry_type}:{use.entry_name}:{use.component_id}:{use.version_tag}" for use in uses)
            ).encode()
        ).hexdigest()
        await self._store.replace_index(instance.id, digest, entries)
        await self._store.commit()
        await self._access.cache(f"studio:indexed:{instance.id}", digest, INDEX_TTL)
        return entries

    async def _stored(self, instance: Instance) -> list[Use]:
        try:
            components = await self._access.system_pages(instance, "/components")
        except AgentOSError:
            return []
        uses: list[Use] = []
        for component in components:
            kind = str(component.get("component_type") or "")
            if kind not in EDITABLE:
                continue
            component_id = str(component["component_id"])
            name = str(component.get("name") or component_id)
            current = component.get("current_version")
            try:
                configs = page_items(
                    await self._access.system_json(
                        instance, f"/components/{component_id}/configs", {"include_config": "true"}
                    )
                )
            except AgentOSError:
                continue
            for config in configs:
                stage = str(config.get("stage") or "draft")
                version = int(config.get("version") or 0)
                tag = f"v{version} draft" if stage == "draft" else f"v{version}"
                if stage != "draft" and version != current:
                    continue
                uses.extend(_uses(kind, component_id, name, tag, config.get("config")))
        return uses

    async def _code(self, instance: Instance) -> list[Use]:
        if BRIDGE_INTROSPECT in await self._access.bridge(instance):
            try:
                body = await self._access.system_json(instance, "/agnostic/v1/introspect/components")
            except AgentOSError:
                body = None
            if body is not None:
                uses: list[Use] = []
                for item in page_items(body):
                    kind = str(item.get("kind") or "")
                    if kind in EDITABLE:
                        component_id = str(item.get("id") or "")
                        name = str(item.get("name") or component_id)
                        uses.extend(_uses(kind, component_id, name, "code", item.get("config")))
                return uses
        return await self._code_from_details(instance)

    async def _code_from_details(self, instance: Instance) -> list[Use]:
        """Without the bridge: the model, tools and members AgentOS lists for components defined in code."""
        uses: list[Use] = []
        for kind in DESCRIBED:
            try:
                items = page_items(await self._access.system_json(instance, f"/{FAMILY[kind]}"))
            except AgentOSError:
                continue
            for item in items:
                if item.get("is_component"):
                    continue
                component_id = str(item.get("id") or "")
                name = str(item.get("name") or component_id)
                uses.extend(
                    Use(entry_type, entry_name, component_id, kind, name, "code")
                    for entry_type, entry_name in _detail_refs(item)
                )
        return uses


def _uses(kind: Kind, component_id: str, name: str, tag: str, config: object) -> list[Use]:
    if not isinstance(config, dict):
        return []
    try:
        parsed = parse(cast("Any", kind), cast("dict[str, Any]", config))
    except ValidationError:
        return []
    return [Use(ref.type, ref.name, component_id, kind, name, tag) for ref in iter_refs(parsed)]


def _detail_refs(item: dict[str, Any]) -> Iterable[tuple[EntryType, str]]:
    model = item.get("model")
    if isinstance(model, dict) and isinstance(model.get("model"), str):  # pyright: ignore[reportUnknownMemberType]
        yield "model", cast("str", model["model"])
    tools = item.get("tools")
    entries = cast("list[Any]", tools.get("tools") or []) if isinstance(tools, dict) else []  # pyright: ignore[reportUnknownMemberType]
    for tool in entries:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):  # pyright: ignore[reportUnknownMemberType]
            yield "tool", cast("str", tool["name"])
    for member in cast("list[Any]", item.get("members") or []):
        if isinstance(member, dict) and isinstance(member.get("id"), str):  # pyright: ignore[reportUnknownMemberType]
            yield ("team" if "members" in member else "agent"), cast("str", member["id"])
