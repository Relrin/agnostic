"""Components in Studio: the index (stored and code-defined), creation, detail, metadata, archive and restore."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_spec.v3_1 import TeamConfig, parse, shape_errors
from agnostic_studio.application.access import (
    CONFLICT,
    DELETE_SCOPE,
    NOT_FOUND,
    READ_SCOPE,
    WRITE_SCOPE,
    StudioAccess,
    detail,
    page_items,
    raise_for,
)
from agnostic_studio.application.ports import StudioStore
from agnostic_studio.domain.model import (
    FAMILY,
    Component,
    ComponentMeta,
    EditableKind,
    Kind,
    Source,
    Version,
    VersionMeta,
    latest,
    open_draft,
)
from agnostic_studio.domain.templates import start_config, template

type CreateMode = Literal["blank", "template", "duplicate", "import"]

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    return _SLUG.sub("-", name.lower()).strip("-")[:120] or "component"


def timestamp(value: object) -> datetime | None:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    return None


def component_of(raw: Mapping[str, Any], source: Source = "studio") -> Component:
    return Component(
        id=str(raw.get("component_id") or raw.get("id") or ""),
        kind=cast("Kind", str(raw.get("component_type") or raw.get("kind") or "agent")),
        name=str(raw.get("name") or raw.get("component_id") or raw.get("id") or ""),
        description=raw.get("description"),
        current_version=raw.get("current_version"),
        created_at=timestamp(raw.get("created_at")) or utcnow(),
        updated_at=timestamp(raw.get("updated_at")),
        deleted_at=timestamp(raw.get("deleted_at")),
        source=source,
        metadata=cast("dict[str, Any]", raw.get("metadata") or {}),
    )


def version_of(raw: Mapping[str, Any]) -> Version:
    return Version(
        component_id=str(raw.get("component_id") or ""),
        version=int(raw.get("version") or 0),
        stage="published" if raw.get("stage") == "published" else "draft",
        label=raw.get("label"),
        notes=raw.get("notes"),
        created_at=timestamp(raw.get("created_at")) or utcnow(),
        updated_at=timestamp(raw.get("updated_at")),
        config=cast("dict[str, Any] | None", raw.get("config")),
        links=cast("list[dict[str, Any]]", raw.get("links") or []),
    )


@dataclass(frozen=True, slots=True)
class VersionView:
    version: Version
    meta: VersionMeta | None
    current: bool


@dataclass(frozen=True, slots=True)
class IndexRow:
    component: Component
    latest_version: int | None
    draft: Version | None
    meta: ComponentMeta | None
    editable: bool


@dataclass(frozen=True, slots=True)
class ComponentDetail:
    instance: Instance
    component: Component
    versions: list[VersionView]
    meta: ComponentMeta | None
    editable: bool

    @property
    def draft(self) -> VersionView | None:
        draft = open_draft([view.version for view in self.versions])
        return next((view for view in self.versions if draft and view.version.version == draft.version), None)

    @property
    def current(self) -> VersionView | None:
        return next((view for view in self.versions if view.current), None)


@dataclass(frozen=True, slots=True)
class CreateRequest:
    kind: EditableKind
    name: str
    mode: CreateMode = "blank"
    component_id: str | None = None
    description: str | None = None
    template_id: str | None = None
    source_id: str | None = None
    source_version: int | None = None
    config: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class MetaPatch:
    name: str | None = None
    description: str | None = None
    owner_group_id: str | None = None
    labels: list[str] | None = None
    clear_owner: bool = False


@dataclass(frozen=True, slots=True)
class Reader:
    """AgentOS reads shared by every studio use case."""

    access: StudioAccess
    store: StudioStore

    async def component(self, principal: Principal, instance: Instance, component_id: str) -> Component:
        response = await self.access.call(principal, instance, "GET", f"/components/{component_id}")
        if response.status == NOT_FOUND:
            raise NotFoundError(f"There is no component {component_id!r} stored on {instance.display_name}.")
        raise_for(instance, response)
        return component_of(cast("dict[str, Any]", response.body))

    async def versions(self, principal: Principal, instance: Instance, component_id: str) -> list[Version]:
        body = await self.access.json(principal, instance, "GET", f"/components/{component_id}/configs")
        return sorted((version_of(item) for item in page_items(body)), key=lambda item: item.version)

    async def version(self, principal: Principal, instance: Instance, component_id: str, version: int) -> Version:
        body = await self.access.json(principal, instance, "GET", f"/components/{component_id}/configs/{version}")
        return version_of(cast("dict[str, Any]", body))

    async def current(self, principal: Principal, instance: Instance, component_id: str) -> Version | None:
        response = await self.access.call(principal, instance, "GET", f"/components/{component_id}/configs/current")
        if response.status == NOT_FOUND:
            return None
        raise_for(instance, response)
        return version_of(cast("dict[str, Any]", response.body))

    async def member_links(
        self, principal: Principal, instance: Instance, config: TeamConfig, pins: Mapping[str, int]
    ) -> list[dict[str, Any]]:
        """Links pinning each stored member at a version (its current one unless pinned); code members get none."""
        links: list[dict[str, Any]] = []
        for position, member in enumerate(config.members or []):
            child = member.component_id
            version = pins.get(child)
            if version is None:
                response = await self.access.call(principal, instance, "GET", f"/components/{child}")
                if response.status == NOT_FOUND or not response.ok:
                    continue
                version = cast("dict[str, Any]", response.body).get("current_version")
                if version is None:
                    continue
            links.append(
                {
                    "link_kind": "member",
                    "link_key": f"member_{position}",
                    "child_component_id": child,
                    "child_version": int(version),
                    "position": position,
                    "meta": {"type": member.type},
                }
            )
        return links


class Components:
    def __init__(self, access: StudioAccess, store: StudioStore, audit: AuditLog) -> None:
        self._access = access
        self._store = store
        self._audit = audit
        self._reader = Reader(access, store)

    @property
    def reader(self) -> Reader:
        return self._reader

    async def index(self, principal: Principal, ref: str, kind: Kind) -> tuple[Instance, list[IndexRow]]:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        stored = await self._access.pages(principal, instance, "/components", {"component_type": kind})
        metas = await self._store.component_metas(instance.id)
        rows: list[IndexRow] = []
        for raw in stored:
            component = component_of(raw)
            versions = await self._reader.versions(principal, instance, component.id)
            newest = latest(versions)
            rows.append(
                IndexRow(
                    component=component,
                    latest_version=newest.version if newest else None,
                    draft=open_draft(versions),
                    meta=metas.get(component.id),
                    editable=kind != "workflow",
                )
            )
        known = {row.component.id for row in rows}
        response = await self._access.call(principal, instance, "GET", f"/{FAMILY[kind]}")
        if response.ok:
            for item in page_items(response.body):
                if item.get("is_component") or str(item.get("id")) in known:
                    continue
                component = component_of({**item, "component_type": kind}, source="code")
                rows.append(IndexRow(component, None, None, metas.get(component.id), editable=False))
        rows.sort(key=lambda row: (row.component.source != "studio", row.component.name.lower()))
        return instance, rows

    async def detail(self, principal: Principal, ref: str, component_id: str) -> ComponentDetail:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        versions = await self._reader.versions(principal, instance, component_id)
        metas = await self._store.version_metas(instance.id, component_id)
        return ComponentDetail(
            instance=instance,
            component=component,
            versions=[
                VersionView(version, metas.get(version.version), version.version == component.current_version)
                for version in reversed(versions)
            ],
            meta=await self._store.component_meta(instance.id, component_id),
            editable=component.kind != "workflow",
        )

    async def create(self, principal: Principal, ref: str, request: CreateRequest) -> ComponentDetail:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        component_id = slug(request.component_id or request.name)
        config = await self._start(principal, instance, request, component_id)
        problems = shape_errors(request.kind, config)
        if problems:
            raise ValidationFailedError(
                "The config doesn't have the shape AgentOS stores.",
                extra={"diagnostics": [problem.as_dict() for problem in problems]},
            )
        parsed = parse(request.kind, config)
        body: dict[str, Any] = {
            "name": request.name,
            "component_type": request.kind,
            "component_id": component_id,
            "description": request.description,
            "config": parsed.dump(),
            "stage": "draft",
            "notes": request.notes,
        }
        response = await self._access.call(principal, instance, "POST", "/components", body=body)
        if response.status == CONFLICT:
            raise ConflictError(f"{instance.display_name} already has a component {component_id!r}: {detail(response)}")
        raise_for(instance, response)
        versions = await self._reader.versions(principal, instance, component_id)
        version = latest(versions)
        if version is not None and isinstance(parsed, TeamConfig):
            links = await self._reader.member_links(principal, instance, parsed, {})
            if links:
                await self._access.json(
                    principal,
                    instance,
                    "PATCH",
                    f"/components/{component_id}/configs/{version.version}",
                    body={"links": links},
                )
        now = utcnow()
        await self._store.save_component_meta(ComponentMeta(instance.id, component_id, request.kind))
        if version is not None:
            await self._store.save_version_meta(
                VersionMeta(
                    instance_id=instance.id,
                    component_id=component_id,
                    version=version.version,
                    author_id=principal.id,
                    author_name=principal.display_name,
                    updated_by=principal.id,
                    updated_by_name=principal.display_name,
                    updated_at=now,
                    notes=request.notes,
                    change_summary=_created_summary(request),
                )
            )
        _ = await self._audit.record(
            AuditEntry(
                action="components.configs.create",
                actor=actor_of(principal),
                resource_kind=request.kind,
                resource_id=component_id,
                resource_display=request.name,
                instance_id=instance.id,
                fields={
                    "component": component_id,
                    "version": f"v{version.version}" if version else "v1",
                    "how": _created_summary(request),
                },
            )
        )
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")
        return await self.detail(principal, instance.id, component_id)

    async def patch(self, principal: Principal, ref: str, component_id: str, patch: MetaPatch) -> ComponentDetail:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        if patch.name is not None or patch.description is not None:
            body = {
                key: value
                for key, value in (("name", patch.name), ("description", patch.description))
                if value is not None
            }
            await self._access.json(principal, instance, "PATCH", f"/components/{component_id}", body=body)
        component = await self._reader.component(principal, instance, component_id)
        meta = await self._store.component_meta(instance.id, component_id) or ComponentMeta(
            instance.id, component_id, component.kind
        )
        meta = replace(
            meta,
            owner_group_id=None if patch.clear_owner else (patch.owner_group_id or meta.owner_group_id),
            labels=tuple(patch.labels) if patch.labels is not None else meta.labels,
        )
        await self._store.save_component_meta(meta)
        await self._store.commit()
        return await self.detail(principal, instance.id, component_id)

    async def archive(self, principal: Principal, ref: str, component_id: str) -> None:
        instance = await self._access.instance(principal, ref, DELETE_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        response = await self._access.call(principal, instance, "DELETE", f"/components/{component_id}")
        if response.status == CONFLICT:
            raise ConflictError(
                f"{component.name} is pinned by other components, so it can't be archived: {detail(response)}",
                extra={"dependents": _dependents(response.body)},
            )
        raise_for(instance, response)
        await self._audited(principal, instance, component, "components.archived")

    async def restore(self, principal: Principal, ref: str, component_id: str) -> ComponentDetail:
        instance = await self._access.instance(principal, ref, DELETE_SCOPE)
        body = await self._access.json(principal, instance, "POST", f"/components/{component_id}/restore")
        await self._audited(principal, instance, component_of(cast("dict[str, Any]", body)), "components.restored")
        return await self.detail(principal, instance.id, component_id)

    async def _audited(self, principal: Principal, instance: Instance, component: Component, action: str) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind=component.kind,
                resource_id=component.id,
                resource_display=component.name,
                instance_id=instance.id,
                fields={"component": component.id, "instance": instance.display_name},
            )
        )
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")

    async def _start(
        self, principal: Principal, instance: Instance, request: CreateRequest, component_id: str
    ) -> dict[str, Any]:
        match request.mode:
            case "blank" | "template":
                chosen = template(request.template_id or f"blank-{request.kind}")
                if chosen is None or chosen.kind != request.kind:
                    raise ValidationFailedError(f"There is no {request.kind} template {request.template_id!r}.")
                return start_config(chosen.config, component_id=component_id, name=request.name, model=request.model)
            case "duplicate":
                if not request.source_id:
                    raise ValidationFailedError("Pick the component to duplicate.")
                source = await self._source_config(principal, instance, request.source_id, request.source_version)
                return {**source, "id": component_id, "name": request.name}
            case "import":
                if not isinstance(request.config, dict):
                    raise ValidationFailedError("Paste or upload the config JSON to import.")
                return {**request.config, "id": component_id, "name": request.name}

    async def _source_config(
        self, principal: Principal, instance: Instance, component_id: str, version: int | None
    ) -> dict[str, Any]:
        if version is not None:
            found = await self._reader.version(principal, instance, component_id, version)
        else:
            versions = await self._reader.versions(principal, instance, component_id)
            current = await self._reader.current(principal, instance, component_id)
            newest = latest(versions)
            target = current.version if current else (newest.version if newest else None)
            if target is None:
                raise NotFoundError(f"{component_id} has no version to duplicate.")
            found = await self._reader.version(principal, instance, component_id, target)
        return dict(found.config or {})


def _created_summary(request: CreateRequest) -> str:
    match request.mode:
        case "blank":
            return "Created from blank"
        case "template":
            chosen = template(request.template_id or "")
            return f"Created from the {chosen.label} template" if chosen else "Created from a template"
        case "duplicate":
            version = f" v{request.source_version}" if request.source_version else ""
            return f"Duplicated from {request.source_id}{version}"
        case "import":
            return "Imported from JSON"


def _dependents(body: object) -> list[str]:
    if isinstance(body, dict):
        raw = cast("dict[str, Any]", body).get("dependents") or cast("dict[str, Any]", body).get("detail")
        if isinstance(raw, list):
            return [str(item) for item in cast("list[Any]", raw)]
    return []
