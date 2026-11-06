"""What other modules may use of Studio: component state, code read with a repository's convention, drafts.

Code sources sit on top of this: they read what Studio has, turn repository files into drafts (never publishing),
bind components to files, and can hold a publish back until the repository caught up (:class:`PublishHold`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_codegen import Parsed, RegistryConvention, Transformed
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError, VersionConflictError
from agnostic_spec.v3_1 import parse, shape_errors
from agnostic_studio.application.access import CONFLICT, NOT_FOUND, StudioAccess, detail, raise_for
from agnostic_studio.application.catalog import UsedByIndex
from agnostic_studio.application.components import Reader, component_of, version_of
from agnostic_studio.application.ports import (
    CatalogTool,
    NoPublishHold,
    NoToolCatalog,
    PublishHold,
    StudioStore,
    ToolCatalogLookup,
)
from agnostic_studio.application.publishing import PUBLISHED_EVENT
from agnostic_studio.application.source import SourceCode, config_hash
from agnostic_studio.domain.diff import diff
from agnostic_studio.domain.model import ComponentMeta, EditableKind, HoldCheck, Kind, VersionMeta, latest, open_draft
from agnostic_studio.domain.registry import CatalogInfo
from agnostic_studio.domain.summaries import change_summary
from agnostic_studio.domain.usage import UsedBy

__all__ = [
    "PUBLISHED_EVENT",
    "CatalogInfo",
    "CatalogTool",
    "ComponentState",
    "DraftCreated",
    "HoldCheck",
    "NoPublishHold",
    "NoToolCatalog",
    "PublishHold",
    "RepositoryDraft",
    "StudioFacade",
    "StudioFacadeImpl",
    "ToolCatalogLookup",
    "UsedBy",
    "VersionSnapshot",
]


@dataclass(frozen=True, slots=True)
class ComponentState:
    id: str
    kind: Kind
    name: str
    current_version: int | None
    latest_version: int | None
    draft_version: int | None
    draft_author_id: str | None = None
    draft_author_name: str | None = None
    draft_updated_at: datetime | None = None
    source_binding_id: str | None = None
    code_path: str | None = None


@dataclass(frozen=True, slots=True)
class VersionSnapshot:
    component_id: str
    version: int
    stage: str
    config: dict[str, Any]
    code: str | None
    """The draft's own code when it is code-backed and still reads as ``config`` (``None`` once the config was saved
    without it, so a caller never writes code that says an older config)."""
    author_id: str | None
    author_name: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class RepositoryDraft:
    """A draft that comes from a repository file: its config, the file's code and who wrote the commit."""

    kind: EditableKind
    component_id: str
    name: str
    config: dict[str, Any]
    code: str
    notes: str
    author_name: str | None = None
    convention: dict[str, Any] | None = None
    binding_id: str | None = None
    code_path: str | None = None


@dataclass(frozen=True, slots=True)
class DraftCreated:
    component_id: str
    version: int
    created_component: bool


class StudioFacade(Protocol):
    async def components(self, principal: Principal, instance: Instance) -> list[ComponentState]:
        """Stored components (without draft details: that takes a call per component, see :meth:`component`)."""
        ...

    async def component(self, principal: Principal, instance: Instance, component_id: str) -> ComponentState | None:
        """The component with its newest draft, or ``None`` when it isn't stored on the instance."""
        ...

    async def snapshot(
        self, principal: Principal, instance: Instance, component_id: str, version: int
    ) -> VersionSnapshot: ...

    async def read_code(
        self,
        principal: Principal,
        instance: Instance,
        kind: Kind | None,
        code: str,
        component_id: str | None,
        convention: RegistryConvention,
    ) -> Parsed:
        """``code`` read into a config, references resolved against what the instance has (never executed)."""
        ...

    async def write_code(
        self,
        principal: Principal,
        instance: Instance,
        kind: Kind,
        code: str,
        config: dict[str, Any],
        component_id: str | None,
        convention: RegistryConvention,
    ) -> Transformed:
        """``code`` edited to say ``config``, keeping comments and formatting."""
        ...

    def summarize(self, before: dict[str, Any], after: dict[str, Any]) -> str:
        """``temperature 0.7 → 0.2, one new instruction``."""
        ...

    async def create_draft(self, principal: Principal, instance: Instance, draft: RepositoryDraft) -> DraftCreated:
        """A new draft (and the component, when the instance doesn't have it yet), code-backed by the file."""
        ...

    async def bind(
        self,
        instance_id: str,
        component_id: str,
        kind: Kind,
        *,
        binding_id: str | None,
        code_path: str | None,
        convention: dict[str, Any] | None,
    ) -> None:
        """Record (or with ``binding_id=None`` clear) the repository file the component is synced with."""
        ...

    async def used_by(self, instance: Instance, entry_type: str, name: str) -> list[UsedBy]:
        """Components (stored drafts and versions, and code) that use a registry entry, as the control plane."""
        ...


class StudioFacadeImpl:
    def __init__(self, access: StudioAccess, store: StudioStore, source: SourceCode, audit: AuditLog) -> None:
        self._access = access
        self._store = store
        self._source = source
        self._audit = audit
        self._reader = Reader(access, store)

    async def components(self, principal: Principal, instance: Instance) -> list[ComponentState]:
        metas = await self._store.component_metas(instance.id)
        states: list[ComponentState] = []
        for raw in await self._access.pages(principal, instance, "/components"):
            component = component_of(raw)
            if component.kind not in {"agent", "team", "workflow"} or not component.id:
                continue
            meta = metas.get(component.id)
            states.append(
                ComponentState(
                    id=component.id,
                    kind=component.kind,
                    name=component.name,
                    current_version=component.current_version,
                    latest_version=None,
                    draft_version=None,
                    source_binding_id=meta.source_binding_id if meta else None,
                    code_path=meta.code_path if meta else None,
                )
            )
        return states

    async def component(self, principal: Principal, instance: Instance, component_id: str) -> ComponentState | None:
        try:
            component = await self._reader.component(principal, instance, component_id)
        except NotFoundError:
            return None
        versions = await self._reader.versions(principal, instance, component_id)
        newest, draft = latest(versions), open_draft(versions)
        draft_meta = await self._store.version_meta(instance.id, component_id, draft.version) if draft else None
        meta = await self._store.component_meta(instance.id, component_id)
        return ComponentState(
            id=component.id,
            kind=component.kind,
            name=component.name,
            current_version=component.current_version,
            latest_version=newest.version if newest else None,
            draft_version=draft.version if draft else None,
            draft_author_id=(draft_meta.updated_by or draft_meta.author_id) if draft_meta else None,
            draft_author_name=(draft_meta.updated_by_name or draft_meta.author_name) if draft_meta else None,
            draft_updated_at=(draft_meta.updated_at if draft_meta else None) or (draft.updated_at if draft else None),
            source_binding_id=meta.source_binding_id if meta else None,
            code_path=meta.code_path if meta else None,
        )

    async def snapshot(
        self, principal: Principal, instance: Instance, component_id: str, version: int
    ) -> VersionSnapshot:
        stored = await self._reader.version(principal, instance, component_id, version)
        meta = await self._store.version_meta(instance.id, component_id, version)
        document = await self._store.code_document(instance.id, component_id, version)
        config = dict(stored.config or {})
        current = document is not None and document.config_hash == config_hash(config)
        return VersionSnapshot(
            component_id=component_id,
            version=version,
            stage=stored.stage,
            config=config,
            code=document.code if document is not None and current else None,
            author_id=(meta.updated_by or meta.author_id) if meta else None,
            author_name=(meta.updated_by_name or meta.author_name) if meta else None,
            updated_at=(meta.updated_at if meta else None) or stored.updated_at or stored.created_at,
        )

    async def read_code(
        self,
        principal: Principal,
        instance: Instance,
        kind: Kind | None,
        code: str,
        component_id: str | None,
        convention: RegistryConvention,
    ) -> Parsed:
        return await self._source.read(principal, instance, kind, code, component_id, convention)

    async def write_code(
        self,
        principal: Principal,
        instance: Instance,
        kind: Kind,
        code: str,
        config: dict[str, Any],
        component_id: str | None,
        convention: RegistryConvention,
    ) -> Transformed:
        return await self._source.write(principal, instance, kind, code, config, component_id, convention)

    def summarize(self, before: dict[str, Any], after: dict[str, Any]) -> str:
        return change_summary(diff(before, after))

    async def create_draft(self, principal: Principal, instance: Instance, draft: RepositoryDraft) -> DraftCreated:
        problems = shape_errors(draft.kind, draft.config)
        if problems:
            raise ValidationFailedError(
                "The file doesn't read as a config AgentOS stores.",
                extra={"diagnostics": [problem.as_dict() for problem in problems]},
            )
        parsed = parse(draft.kind, draft.config)
        config = parsed.dump()
        existing = await self._access.call(principal, instance, "GET", f"/components/{draft.component_id}")
        created = existing.status == NOT_FOUND
        based_on: int | None = None
        if created:
            response = await self._access.call(
                principal,
                instance,
                "POST",
                "/components",
                body={
                    "name": draft.name,
                    "component_type": draft.kind,
                    "component_id": draft.component_id,
                    "config": config,
                    "stage": "draft",
                    "notes": draft.notes,
                },
            )
            if response.status == CONFLICT:
                raise ConflictError(f"{instance.display_name} already has {draft.component_id}: {detail(response)}")
            raise_for(instance, response)
            newest = latest(await self._reader.versions(principal, instance, draft.component_id))
            if newest is None:
                raise NotFoundError(f"{instance.display_name} stored {draft.component_id} without a version.")
            number = newest.version
        else:
            raise_for(instance, existing)
            newest = latest(await self._reader.versions(principal, instance, draft.component_id))
            based_on = newest.version if newest else None
            response = await self._access.call(
                principal,
                instance,
                "POST",
                f"/components/{draft.component_id}/configs",
                body={
                    "config": config,
                    "stage": "draft",
                    "set_current": False,
                    "notes": draft.notes,
                    "guard": {"latest_version": based_on or 0},
                },
            )
            if response.status == CONFLICT:
                raise VersionConflictError(
                    f"Someone created another version of {draft.component_id} meanwhile: {detail(response)}"
                )
            raise_for(instance, response)
            number = version_of(cast("dict[str, Any]", response.body)).version
        links = await self._reader.links_for(principal, instance, parsed, {})
        if links:
            await self._access.json(
                principal,
                instance,
                "PATCH",
                f"/components/{draft.component_id}/configs/{number}",
                body={"links": links},
            )
        convention = RegistryConvention.from_dict(draft.convention)
        _ = await self._source.keep(
            principal, instance, draft.component_id, draft.kind, number, draft.code, config, convention
        )
        person = principal.kind != "system"
        await self._store.save_version_meta(
            VersionMeta(
                instance_id=instance.id,
                component_id=draft.component_id,
                version=number,
                author_id=principal.id if person else None,
                author_name=draft.author_name or principal.display_name,
                updated_by=principal.id if person else None,
                updated_by_name=draft.author_name or principal.display_name,
                updated_at=utcnow(),
                notes=draft.notes,
                change_summary=draft.notes,
                based_on_version=based_on,
            )
        )
        meta = await self._store.component_meta(instance.id, draft.component_id) or ComponentMeta(
            instance.id, draft.component_id, draft.kind
        )
        await self._store.save_component_meta(
            replace(
                meta,
                source_binding_id=draft.binding_id or meta.source_binding_id,
                code_path=draft.code_path or meta.code_path,
                convention=draft.convention if draft.binding_id else meta.convention,
            )
        )
        _ = await self._audit.record(
            AuditEntry(
                action="components.configs.create",
                actor=actor_of(principal),
                resource_kind=draft.kind,
                resource_id=draft.component_id,
                resource_display=draft.name,
                instance_id=instance.id,
                via="system" if not person else "web",
                fields={"component": draft.component_id, "version": f"v{number}", "how": draft.notes},
            )
        )
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")
        return DraftCreated(draft.component_id, number, created)

    async def bind(
        self,
        instance_id: str,
        component_id: str,
        kind: Kind,
        *,
        binding_id: str | None,
        code_path: str | None,
        convention: dict[str, Any] | None,
    ) -> None:
        meta = await self._store.component_meta(instance_id, component_id) or ComponentMeta(
            instance_id, component_id, kind
        )
        await self._store.save_component_meta(
            replace(
                meta,
                source_binding_id=binding_id,
                code_path=code_path if binding_id else None,
                convention=convention if binding_id else None,
            )
        )
        await self._store.commit()

    async def used_by(self, instance: Instance, entry_type: str, name: str) -> list[UsedBy]:
        index = await UsedByIndex(self._access, self._store).ensure(instance)
        return index.get((entry_type, name), [])
