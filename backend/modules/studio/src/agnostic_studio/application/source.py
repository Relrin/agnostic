"""The editable code pane: code read back into a config, and form edits written into code.

It also keeps the code of code-backed drafts.

References in code resolve against what the instance has: the draft's own config first (so a tool reads back exactly
as it is stored), then the registry and the stored components. Parsing and edits run on the source workers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, cast

import orjson

from agnostic_codegen import (
    FOLDERS,
    Lookup,
    Parsed,
    RegistryConvention,
    RuffResult,
    Transformed,
    lint,
    snake,
)
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_spec.v3_1 import Kind as SpecKind
from agnostic_spec.v3_1 import RefType, parse, shape_errors
from agnostic_studio.application.access import READ_SCOPE, WRITE_SCOPE, StudioAccess
from agnostic_studio.application.catalog import RegistryCatalog
from agnostic_studio.application.components import Reader
from agnostic_studio.application.ports import SourceRunner, StudioStore
from agnostic_studio.application.source_jobs import parse_job, transform_job
from agnostic_studio.domain.model import CodeDocument, latest
from agnostic_studio.domain.registry import tool_entry

LOOKUP_TTL = 60.0
CONVENTION = RegistryConvention()


def fingerprint(convention: RegistryConvention) -> str:
    """Short and stable per convention, so cached lookups of different repositories don't mix."""
    if convention == CONVENTION:
        return "default"
    return hashlib.sha256(orjson.dumps(convention.as_dict(), option=orjson.OPT_SORT_KEYS)).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class SourceView:
    parsed: Parsed
    ruff: RuffResult


@dataclass(frozen=True, slots=True)
class TransformView:
    transformed: Transformed
    ruff: RuffResult


@dataclass(frozen=True, slots=True)
class DocumentView:
    document: CodeDocument | None
    stale: bool
    """The draft changed since the code was saved (somewhere that didn't write the code), so they disagree."""


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(orjson.dumps(config, option=orjson.OPT_SORT_KEYS)).hexdigest()


class SourceCode:
    def __init__(
        self, access: StudioAccess, catalog: RegistryCatalog, store: StudioStore, runner: SourceRunner
    ) -> None:
        self._access = access
        self._catalog = catalog
        self._store = store
        self._runner = runner
        self._reader = Reader(access, store)

    async def parse(
        self, principal: Principal, ref: str, kind: SpecKind, code: str, component_id: str | None = None
    ) -> SourceView:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        convention = await self.convention_for(instance.id, component_id)
        parsed = await self.read(principal, instance, kind, code, component_id, convention)
        return SourceView(parsed, await _lint(code, kind, parsed, convention))

    async def convention_for(self, instance_id: str, component_id: str | None) -> RegistryConvention:
        """The bound repository's convention for ``component_id``; the default one otherwise."""
        if component_id is None:
            return CONVENTION
        meta = await self._store.component_meta(instance_id, component_id)
        return RegistryConvention.from_dict(meta.convention) if meta is not None and meta.convention else CONVENTION

    async def read(
        self,
        principal: Principal,
        instance: Instance,
        kind: SpecKind | None,
        code: str,
        component_id: str | None,
        convention: RegistryConvention = CONVENTION,
    ) -> Parsed:
        lookup = await self.lookup(principal, instance, component_id, convention)
        return await self._runner.run(parse_job, code, kind, component_id, convention, lookup)

    async def write(
        self,
        principal: Principal,
        instance: Instance,
        kind: SpecKind,
        code: str,
        after: dict[str, Any],
        component_id: str | None,
        convention: RegistryConvention = CONVENTION,
    ) -> Transformed:
        """``code`` edited to say ``after``, keeping its formatting (no scope check: callers did theirs)."""
        lookup = await self.lookup(principal, instance, component_id, convention)
        return await self._runner.run(transform_job, code, after, kind, component_id, convention, lookup)

    async def transform(
        self,
        principal: Principal,
        ref: str,
        kind: SpecKind,
        code: str,
        after: dict[str, Any],
        component_id: str | None = None,
    ) -> TransformView:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        problems = shape_errors(kind, after)
        if problems:
            raise ValidationFailedError(
                "The config doesn't have the shape AgentOS stores.",
                extra={"diagnostics": [problem.as_dict() for problem in problems]},
            )
        convention = await self.convention_for(instance.id, component_id)
        result = await self.write(principal, instance, kind, code, after, component_id, convention)
        parsed = Parsed(kind, None, result.config, result.diagnostics, result.spans, result.code_owned)
        return TransformView(result, await _lint(result.code, kind, parsed, convention))

    # ---------------------------------------------------------------- code-backed drafts

    async def document(self, principal: Principal, ref: str, component_id: str, version: int) -> DocumentView:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        stored = await self._reader.version(principal, instance, component_id, version)
        document = await self._store.code_document(instance.id, component_id, version)
        if document is None:
            return DocumentView(None, stale=False)
        return DocumentView(document, stale=document.config_hash != config_hash(stored.config or {}))

    async def keep(
        self,
        principal: Principal,
        instance: Instance,
        component_id: str,
        kind: SpecKind,
        version: int,
        code: str,
        config: dict[str, Any],
        convention: RegistryConvention | None = None,
    ) -> CodeDocument:
        """Check that ``code`` reads as ``config`` before it is stored as the draft's code (no commit)."""
        await self._access.require(principal, WRITE_SCOPE, instance)
        if convention is None:
            convention = await self.convention_for(instance.id, component_id)
        parsed = await self.read(principal, instance, kind, code, component_id, convention)
        expected = parse(kind, config).dump()
        if parsed.config != expected:
            problems = [item.as_dict() for item in parsed.diagnostics if item.severity == "error"]
            raise ValidationFailedError(
                "The code doesn't read as the config being saved; save them together once the code parses.",
                extra={"diagnostics": problems},
            )
        document = CodeDocument(
            instance_id=instance.id,
            component_id=component_id,
            version=version,
            code=code,
            config_hash=config_hash(expected),
            updated_by=principal.id,
            updated_by_name=principal.display_name,
            updated_at=utcnow(),
        )
        await self._store.save_code_document(document)
        return document

    # ---------------------------------------------------------------- what references resolve to

    async def lookup(
        self,
        principal: Principal,
        instance: Instance,
        component_id: str | None,
        convention: RegistryConvention = CONVENTION,
    ) -> Lookup:
        lookup = Lookup(convention)
        if component_id is not None:
            for config, kind in await self._known_configs(principal, instance, component_id):
                try:
                    _ = lookup.learn([parse(kind, config)])
                except ValueError:
                    continue
        for ref_type, attribute, value in await self._entries(principal, instance, convention):
            lookup.entries.setdefault((ref_type, attribute), value)
        return lookup

    async def _known_configs(
        self, principal: Principal, instance: Instance, component_id: str
    ) -> list[tuple[dict[str, Any], SpecKind]]:
        """The configs of the component's newest and current versions: what its references are stored as."""
        try:
            component = await self._reader.component(principal, instance, component_id)
        except NotFoundError:
            return []
        newest = latest(await self._reader.versions(principal, instance, component_id))
        numbers = {number for number in (newest.version if newest else None, component.current_version) if number}
        found: list[tuple[dict[str, Any], SpecKind]] = []
        for number in sorted(numbers, reverse=True):
            version = await self._reader.version(principal, instance, component_id, number)
            if version.config:
                found.append((version.config, component.kind))
        return found

    async def _entries(
        self, principal: Principal, instance: Instance, convention: RegistryConvention
    ) -> list[tuple[str, str, object]]:
        """``(ref_type, attribute, stored value)`` for the registry and the stored components, cached briefly."""
        key = f"studio:lookup:{instance.id}:{fingerprint(convention)}"
        cached = await self._access.cached(key)
        if isinstance(cached, list):
            return [(str(item[0]), str(item[1]), item[2]) for item in cast("list[list[Any]]", cached)]
        entries: list[tuple[str, str, object]] = []
        _, catalog = await self._catalog.catalog(principal, instance.id)
        for entry in catalog.entries:
            name = (
                entry.id if entry.type in {"agent", "team", "workflow", "memory_manager"} and entry.id else entry.name
            )
            value = _stored(entry.type, name, entry)
            if value is not None:
                entries.append((entry.type, convention.attribute(cast("RefType", entry.type), entry.name), value))
        for item in await self._access.pages(principal, instance, "/components"):
            kind = str(item.get("component_type") or "")
            component = str(item.get("component_id") or "")
            if kind in FOLDERS and component:
                entries.append((kind, snake(component), component))
        await self._access.cache(key, [list(entry) for entry in entries], LOOKUP_TTL)
        return entries


def _stored(entry_type: str, name: str, entry: Any) -> object | None:  # noqa: ANN401, PLR0911
    match entry_type:
        case "tool":
            return tool_entry(entry)
        case "model":
            model_id = str(entry.metadata.get("model_id") or entry.name)
            provider = entry.metadata.get("provider")
            return {"id": model_id, "provider": provider} if provider else {"id": model_id}
        case "knowledge" | "learning":
            return {"name": entry.name}
        case "schema":
            return entry.name
        case "memory_manager":
            return {"registry_id": name}
        case "agent" | "team" | "workflow" | "function":
            return name
        case _:
            return None


async def _lint(code: str, kind: SpecKind | None, parsed: Parsed, convention: RegistryConvention) -> RuffResult:
    folder = FOLDERS.get(kind or "agent", "agents")
    return await lint(
        code, filename=f"{folder}/{parsed.variable or 'component'}.py", first_party=convention.first_party
    )
