"""Drafts: autosave with a conflict check, a new draft from any version, discarding a draft, and diffs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_codegen import counts as line_counts
from agnostic_codegen import render, unified
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, ValidationFailedError, VersionConflictError
from agnostic_spec.v3_1 import Kind as SpecKind
from agnostic_spec.v3_1 import TeamConfig, parse, shape_errors
from agnostic_studio.application.access import CONFLICT, READ_SCOPE, WRITE_SCOPE, StudioAccess, detail, raise_for
from agnostic_studio.application.components import Reader, VersionView, version_of
from agnostic_studio.application.ports import StudioStore
from agnostic_studio.domain.diff import DiffCounts, FieldChange, counts, diff
from agnostic_studio.domain.model import Component, Version, VersionMeta, latest
from agnostic_studio.domain.summaries import change_summary


class DraftConflictError(VersionConflictError):
    title = "Someone else saved this draft first"


def revision(version: Version, meta: VersionMeta | None) -> str:
    """Changes whenever the draft is saved, from Studio or straight on AgentOS."""
    stamp = version.updated_at or version.created_at
    saved = meta.updated_at.isoformat() if meta is not None and meta.updated_at is not None else ""
    return f"{int(stamp.timestamp() * 1000)}:{saved}"


@dataclass(frozen=True, slots=True)
class SaveDraft:
    config: dict[str, Any]
    revision: str | None = None
    """What the editor loaded; ``None`` skips the check (last writer wins)."""
    pins: Mapping[str, int] | None = None
    notes: str | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class Diff:
    component: Component
    from_version: int
    to_version: int
    changes: list[FieldChange]
    counts: DiffCounts
    summary: str
    code_before: str
    code_after: str
    unified: str
    lines_added: int
    lines_removed: int


class Drafts:
    def __init__(self, access: StudioAccess, store: StudioStore, audit: AuditLog) -> None:
        self._access = access
        self._store = store
        self._audit = audit
        self._reader = Reader(access, store)

    async def version(
        self, principal: Principal, ref: str, component_id: str, number: int
    ) -> tuple[Instance, VersionView]:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        version = await self._reader.version(principal, instance, component_id, number)
        meta = await self._store.version_meta(instance.id, component_id, number)
        return instance, VersionView(version, meta, version.version == component.current_version)

    async def save(
        self, principal: Principal, ref: str, component_id: str, number: int, request: SaveDraft
    ) -> VersionView:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        stored = await self._reader.version(principal, instance, component_id, number)
        if stored.stage != "draft":
            raise ConflictError(f"v{number} is published and can't change; start a new draft from it.")
        meta = await self._store.version_meta(instance.id, component_id, number)
        if request.revision is not None and request.revision != revision(stored, meta):
            raise _conflict(stored, meta)
        kind = cast("SpecKind", component.kind)
        problems = shape_errors(kind, request.config)
        if problems:
            raise ValidationFailedError(
                "The draft doesn't have the shape AgentOS stores.",
                extra={"diagnostics": [problem.as_dict() for problem in problems]},
            )
        parsed = parse(kind, request.config)
        versions = await self._reader.versions(principal, instance, component_id)
        newest = latest(versions)
        body: dict[str, Any] = {
            "config": parsed.dump(),
            "guard": {"latest_version": newest.version if newest else number},
        }
        if request.notes is not None:
            body["notes"] = request.notes
        if request.label is not None:
            body["label"] = request.label
        if isinstance(parsed, TeamConfig):
            body["links"] = await self._reader.member_links(principal, instance, parsed, request.pins or _pins(stored))
        response = await self._access.call(
            principal, instance, "PATCH", f"/components/{component_id}/configs/{number}", body=body
        )
        if response.status == CONFLICT:
            fresh = await self._reader.version(principal, instance, component_id, number)
            raise _conflict(fresh, await self._store.version_meta(instance.id, component_id, number))
        raise_for(instance, response)
        saved = version_of(cast("dict[str, Any]", response.body))
        now = utcnow()
        updated = replace(
            meta
            or VersionMeta(
                instance.id, component_id, number, author_id=principal.id, author_name=principal.display_name
            ),
            updated_by=principal.id,
            updated_by_name=principal.display_name,
            updated_at=now,
            notes=request.notes if request.notes is not None else (meta.notes if meta else None),
        )
        await self._store.save_version_meta(updated)
        await self._store.commit()
        await self._access.forget(f"studio:indexed:{instance.id}")
        return VersionView(saved, updated, current=False)

    async def new_draft(
        self, principal: Principal, ref: str, component_id: str, from_version: int | None, notes: str | None = None
    ) -> VersionView:
        """A new draft vN+1 with the config (and member pins) of ``from_version`` (default: the current version)."""
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        versions = await self._reader.versions(principal, instance, component_id)
        newest = latest(versions)
        base_number = from_version or component.current_version or (newest.version if newest else None)
        if base_number is None:
            raise ValidationFailedError(f"{component.name} has no version to start a draft from.")
        base = await self._reader.version(principal, instance, component_id, base_number)
        body: dict[str, Any] = {
            "config": base.config or {},
            "stage": "draft",
            "set_current": False,
            "notes": notes,
            "guard": {"latest_version": newest.version if newest else 0},
        }
        if base.links:
            body["links"] = base.links
        response = await self._access.call(
            principal, instance, "POST", f"/components/{component_id}/configs", body=body
        )
        if response.status == CONFLICT:
            raise VersionConflictError(
                f"Someone created another version of {component.name} meanwhile: {detail(response)}"
            )
        raise_for(instance, response)
        created = version_of(cast("dict[str, Any]", response.body))
        meta = VersionMeta(
            instance_id=instance.id,
            component_id=component_id,
            version=created.version,
            author_id=principal.id,
            author_name=principal.display_name,
            updated_by=principal.id,
            updated_by_name=principal.display_name,
            updated_at=utcnow(),
            notes=notes,
            based_on_version=base_number,
            change_summary=f"Based on v{base_number}",
        )
        await self._store.save_version_meta(meta)
        _ = await self._audit.record(
            AuditEntry(
                action="components.configs.create",
                actor=actor_of(principal),
                resource_kind=component.kind,
                resource_id=component_id,
                resource_display=component.name,
                instance_id=instance.id,
                fields={"component": component_id, "version": f"v{created.version}", "how": f"Based on v{base_number}"},
            )
        )
        await self._store.commit()
        return VersionView(created, meta, current=False)

    async def discard(self, principal: Principal, ref: str, component_id: str, number: int) -> None:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        stored = await self._reader.version(principal, instance, component_id, number)
        if stored.stage != "draft":
            raise ConflictError(f"v{number} is published; published versions are kept.")
        await self._access.json(principal, instance, "DELETE", f"/components/{component_id}/configs/{number}")
        await self._access.forget(f"studio:indexed:{instance.id}")

    async def diff(self, principal: Principal, ref: str, component_id: str, from_version: int, to_version: int) -> Diff:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        component = await self._reader.component(principal, instance, component_id)
        before = await self._reader.version(principal, instance, component_id, from_version)
        after = await self._reader.version(principal, instance, component_id, to_version)
        return await describe(component, before, after)


async def describe(component: Component, before: Version, after: Version) -> Diff:
    changes = diff(before.config or {}, after.config or {})
    kind = cast("SpecKind", component.kind)
    rendered_before = await render(parse(kind, before.config or {}))
    rendered_after = await render(parse(kind, after.config or {}))
    added, removed = line_counts(rendered_before.code, rendered_after.code)
    return Diff(
        component=component,
        from_version=before.version,
        to_version=after.version,
        changes=changes,
        counts=counts(changes),
        summary=change_summary(changes),
        code_before=rendered_before.code,
        code_after=rendered_after.code,
        unified=unified(
            rendered_before.code,
            rendered_after.code,
            from_label=f"v{before.version}/{rendered_before.filename}",
            to_label=f"v{after.version}/{rendered_after.filename}",
        ),
        lines_added=added,
        lines_removed=removed,
    )


def _pins(version: Version) -> dict[str, int]:
    return {
        str(link["child_component_id"]): int(link["child_version"])
        for link in version.links
        if link.get("link_kind") == "member"
        and link.get("child_component_id")
        and link.get("child_version") is not None
    }


def _conflict(version: Version, meta: VersionMeta | None) -> DraftConflictError:
    who = meta.updated_by_name if meta is not None and meta.updated_by_name else "Someone"
    return DraftConflictError(
        f"{who} saved v{version.version} after you opened it. Review their version before saving yours.",
        extra={
            "version": version.version,
            "revision": revision(version, meta),
            "saved_by": meta.updated_by_name if meta else None,
            "saved_at": meta.updated_at.isoformat() if meta and meta.updated_at else None,
            "config": version.config,
        },
    )
