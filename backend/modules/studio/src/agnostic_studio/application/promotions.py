"""Promote a published version to another instance: dry run against the target's registry, then create drafts there."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_spec.v3_1 import Kind as SpecKind
from agnostic_spec.v3_1 import iter_refs, parse
from agnostic_studio.application.access import (
    NOT_FOUND,
    PROMOTE_SCOPE,
    READ_SCOPE,
    WRITE_SCOPE,
    StudioAccess,
    raise_for,
)
from agnostic_studio.application.catalog import RegistryCatalog
from agnostic_studio.application.components import Reader, version_of
from agnostic_studio.application.ports import StudioStore
from agnostic_studio.application.publishing import Publisher
from agnostic_studio.domain.model import ComponentMeta, Version, VersionMeta, latest
from agnostic_studio.domain.promotion import Promotion, Reference, check, report_dict


@dataclass(frozen=True, slots=True)
class PromoteRequest:
    target: str
    version: int | None = None
    include_children: bool = True


@dataclass(frozen=True, slots=True)
class _Child:
    component_id: str
    kind: str
    version: int | None


class Promotions:
    def __init__(
        self,
        access: StudioAccess,
        store: StudioStore,
        audit: AuditLog,
        catalog: RegistryCatalog,
        publisher: Publisher,
    ) -> None:
        self._access = access
        self._store = store
        self._audit = audit
        self._catalog = catalog
        self._publisher = publisher
        self._reader = Reader(access, store)

    async def list(self, principal: Principal, ref: str, component_id: str) -> list[Promotion]:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        return await self._store.promotions(instance.id, component_id)

    async def dry_run(self, principal: Principal, ref: str, component_id: str, request: PromoteRequest) -> Promotion:
        source = await self._access.instance(principal, ref, READ_SCOPE)
        target = await self._access.instance(principal, request.target, READ_SCOPE)
        if target.id == source.id:
            raise ValidationFailedError("Pick another instance to promote to.")
        await self._access.require(principal, PROMOTE_SCOPE, source)
        await self._access.require(principal, PROMOTE_SCOPE, target)
        component = await self._reader.component(principal, source, component_id)
        number = request.version or component.current_version
        if number is None:
            raise ConflictError(f"{component.name} has no published version to promote.")
        version = await self._reader.version(principal, source, component_id, number)
        if version.stage != "published":
            raise ConflictError(f"v{number} is a draft; publish it before promoting it.")
        report = await self._report(principal, target, component.kind, version, request.include_children)
        promotion = Promotion(
            id=new_id("prm"),
            from_instance=source.id,
            to_instance=target.id,
            component_id=component_id,
            component_kind=component.kind,
            from_version=number,
            to_version=None,
            include_children=request.include_children,
            status="dry_run" if report["ok"] else "blocked",
            report=report,
            created_by=principal.id,
            created_by_name=principal.display_name,
            created_at=utcnow(),
        )
        await self._store.add_promotion(promotion)
        await self._store.commit()
        return promotion

    async def apply(self, principal: Principal, ref: str, promotion_id: str, *, publish: bool) -> Promotion:
        source = await self._access.instance(principal, ref, READ_SCOPE)
        promotion = await self._store.promotion(promotion_id)
        if promotion is None or promotion.from_instance != source.id:
            raise NotFoundError(f"There is no promotion {promotion_id} from {source.display_name}.")
        if promotion.status != "dry_run":
            raise ConflictError(f"This promotion is {promotion.status.replace('_', ' ')}; run a new dry run.")
        target = await self._access.instance(principal, promotion.to_instance, WRITE_SCOPE)
        await self._access.require(principal, PROMOTE_SCOPE, source)
        await self._access.require(principal, PROMOTE_SCOPE, target)
        version = await self._reader.version(principal, source, promotion.component_id, promotion.from_version)
        report = await self._report(principal, target, promotion.component_kind, version, promotion.include_children)
        if not report["ok"]:
            await self._store.save_promotion(replace(promotion, status="blocked", report=report))
            await self._store.commit()
            raise ConflictError(str(report["summary"]), extra={"report": report})

        pinned: dict[str, int] = {}
        for child in _children(version):
            status = _child_status(report, child.component_id)
            if status == "promoted_together" and child.version is not None:
                child_version = await self._reader.version(principal, source, child.component_id, child.version)
                child_component = await self._reader.component(principal, source, child.component_id)
                pinned[child.component_id] = await self._copy(
                    principal, source, target, child_component.name, child.kind, child_version
                )
        component = await self._reader.component(principal, source, promotion.component_id)
        links = [
            {**link, "child_version": pinned.get(str(link.get("child_component_id")), link.get("child_version"))}
            for link in version.links
            if str(link.get("child_component_id")) in pinned
            or _child_status(report, str(link.get("child_component_id"))) == "present"
        ]
        links = [await self._present_pin(principal, target, link, pinned) for link in links]
        to_version = await self._copy(
            principal, source, target, component.name, promotion.component_kind, replace(version, links=links)
        )
        applied = replace(promotion, status="applied", to_version=to_version, report=report, applied_at=utcnow())
        await self._store.save_promotion(applied)
        _ = await self._audit.record(
            AuditEntry(
                action="studio.promote",
                actor=actor_of(principal),
                resource_kind=promotion.component_kind,
                resource_id=promotion.component_id,
                resource_display=component.name,
                instance_id=target.id,
                fields={
                    "component": component.name,
                    "from": f"{source.display_name} v{promotion.from_version}",
                    "to": f"{target.display_name} v{to_version}",
                    "outcome": "published" if publish else "as a draft",
                },
                links={"source_instance": source.id, "promotion": promotion.id},
            )
        )
        await self._store.commit()
        if publish:
            await self._publisher.publish(
                principal,
                target.id,
                promotion.component_id,
                to_version,
                notes=f"Promoted from {source.display_name} v{promotion.from_version}",
            )
            applied = replace(applied, status="published")
            await self._store.save_promotion(applied)
            await self._store.commit()
        return applied

    async def _report(
        self, principal: Principal, target: Instance, kind: str, version: Version, include_children: bool
    ) -> dict[str, object]:
        parsed = parse(cast("SpecKind", kind), version.config or {})
        references = [Reference(ref.path, ref.type, ref.name) for ref in iter_refs(parsed)]
        # The check is about the target as it is now, not as the gateway cached it.
        await self._access.gateway.invalidate(target)
        entries = await self._catalog.entries(principal, target)
        names = {(entry.type, entry.name) for entry in entries} | {
            ("memory_manager", entry.id) for entry in entries if entry.type == "memory_manager" and entry.id
        }
        stored = {str(item.get("component_id")) for item in await self._access.pages(principal, target, "/components")}
        children = [(child.component_id, child.kind, child.version) for child in _children(version)]
        members = {child[0] for child in children}
        children.extend(
            (ref.name, ref.type, None)
            for ref in references
            if ref.type in {"agent", "team"} and ref.name not in members
        )
        return report_dict(check(references, names, children, stored, include_children=include_children))

    async def _present_pin(
        self, principal: Principal, target: Instance, link: dict[str, Any], pinned: dict[str, int]
    ) -> dict[str, Any]:
        child = str(link.get("child_component_id"))
        if child in pinned:
            return link
        response = await self._access.call(principal, target, "GET", f"/components/{child}")
        current = cast("dict[str, Any]", response.body).get("current_version") if response.ok else None
        return {**link, "child_version": current} if current is not None else link

    async def _copy(
        self, principal: Principal, source: Instance, target: Instance, name: str, kind: str, version: Version
    ) -> int:
        """Create the component on the target, or add a draft to it; returns the new version number there."""
        component_id = version.component_id
        existing = await self._access.call(principal, target, "GET", f"/components/{component_id}")
        if existing.status == NOT_FOUND:
            created = await self._access.call(
                principal,
                target,
                "POST",
                "/components",
                body={
                    "name": name,
                    "component_type": kind,
                    "component_id": component_id,
                    "config": version.config or {},
                    "stage": "draft",
                    "notes": f"Promoted from {source.display_name} v{version.version}",
                },
            )
            raise_for(target, created)
            versions = await self._reader.versions(principal, target, component_id)
            newest = latest(versions)
            number = newest.version if newest else 1
            if version.links:
                await self._access.json(
                    principal,
                    target,
                    "PATCH",
                    f"/components/{component_id}/configs/{number}",
                    body={"links": version.links},
                )
            await self._store.save_component_meta(ComponentMeta(target.id, component_id, cast("Any", kind)))
        else:
            raise_for(target, existing)
            body: dict[str, Any] = {
                "config": version.config or {},
                "stage": "draft",
                "set_current": False,
                "notes": f"Promoted from {source.display_name} v{version.version}",
            }
            if version.links:
                body["links"] = version.links
            number = version_of(
                cast(
                    "dict[str, Any]",
                    await self._access.json(
                        principal, target, "POST", f"/components/{component_id}/configs", body=body
                    ),
                )
            ).version
        await self._store.save_version_meta(
            VersionMeta(
                instance_id=target.id,
                component_id=component_id,
                version=number,
                author_id=principal.id,
                author_name=principal.display_name,
                updated_by=principal.id,
                updated_by_name=principal.display_name,
                updated_at=utcnow(),
                change_summary=f"Promoted from {source.display_name} v{version.version}",
                promoted_from={"instance_id": source.id, "instance": source.display_name, "version": version.version},
            )
        )
        await self._access.forget(f"studio:indexed:{target.id}")
        return number


def _children(version: Version) -> list[_Child]:
    return [
        _Child(
            str(link["child_component_id"]),
            str(cast("dict[str, Any]", link.get("meta") or {}).get("type") or "agent"),
            int(link["child_version"]) if link.get("child_version") is not None else None,
        )
        for link in version.links
        if link.get("link_kind") == "member" and link.get("child_component_id")
    ]


def _child_status(report: dict[str, object], component_id: str) -> str | None:
    for child in cast("list[dict[str, Any]]", report.get("children") or []):
        if child.get("component_id") == component_id:
            return str(child.get("status"))
    return None
