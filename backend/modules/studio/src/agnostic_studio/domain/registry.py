"""Registry entries as Studio shows them: a one-line meta, details, flags and whether Studio may build with them."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

type EntryType = Literal[
    "tool",
    "model",
    "db",
    "vector_db",
    "schema",
    "function",
    "knowledge",
    "memory_manager",
    "session_summary_manager",
    "learning",
    "agent",
    "team",
    "workflow",
]
type Status = Literal["registered", "discovered"]
type AvailabilityKind = Literal["available", "unavailable", "registered"]

ENTRY_TYPES: tuple[EntryType, ...] = (
    "tool",
    "model",
    "db",
    "vector_db",
    "schema",
    "function",
    "knowledge",
    "memory_manager",
    "session_summary_manager",
    "learning",
    "agent",
    "team",
    "workflow",
)
TYPE_LABELS: dict[EntryType, str] = {
    "tool": "Tool",
    "model": "Model",
    "db": "Database",
    "vector_db": "Vector DB",
    "schema": "Schema",
    "function": "Function",
    "knowledge": "Knowledge",
    "memory_manager": "Memory manager",
    "session_summary_manager": "Summary manager",
    "learning": "Learning machine",
    "agent": "Agent",
    "team": "Team",
    "workflow": "Workflow",
}
DETAIL_KEYS = (
    "class_path",
    "module",
    "qualname",
    "signature",
    "provider",
    "model_id",
    "db_id",
    "vector_db_id",
    "table_name",
    "collection",
    "vector_db_class",
    "contents_db_class",
    "max_results",
    "num_readers",
    "id",
)


@dataclass(frozen=True, slots=True)
class Source:
    """Where the entry is defined, as the bridge reports it."""

    module: str | None = None
    file: str | None = None
    line: int | None = None
    declared: bool = True
    requires_confirmation: bool = False
    approval_type: str | None = None


@dataclass(frozen=True, slots=True)
class Function:
    name: str
    description: str | None
    parameters: dict[str, Any] | None
    signature: str | None
    requires_confirmation: bool
    external_execution: bool


@dataclass(frozen=True, slots=True)
class Availability:
    kind: AvailabilityKind
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    type: EntryType
    name: str
    id: str | None
    description: str | None
    meta: str
    status: Status
    details: list[tuple[str, str]]
    code: str | None
    code_label: str | None
    requires_approval: bool
    approval_type: str | None
    availability: Availability
    functions: list[Function] = field(default_factory=list[Function])
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    source: Source | None = None

    @property
    def studio_available(self) -> bool:
        return self.availability.kind != "unavailable"

    @property
    def blurb(self) -> str:
        if self.description:
            return self.description.strip().splitlines()[0]
        if self.status == "discovered":
            return "Found on a component that is defined in code."
        return f"{TYPE_LABELS[self.type]} registered in registry.py."


def normalize(raw: Mapping[str, Any], source: Source | None = None) -> RegistryEntry:
    """One ``GET /registry`` item, enriched by the bridge's ``source`` answer when there is one."""
    entry_type = cast("EntryType", str(raw.get("type") or "tool"))
    name = str(raw.get("name") or "")
    metadata = cast("dict[str, Any]", raw.get("metadata") or {})
    functions = _functions(metadata)
    requires_approval = bool(
        metadata.get("requires_confirmation")
        or any(function.requires_confirmation for function in functions)
        or (source is not None and (source.requires_confirmation or source.approval_type))
    )
    status: Status = "discovered" if source is not None and not source.declared else "registered"
    code, code_label = _code(entry_type, metadata)
    return RegistryEntry(
        type=entry_type,
        name=name,
        id=str(raw["id"]) if raw.get("id") else None,
        description=str(raw["description"]) if raw.get("description") else None,
        meta=meta_line(entry_type, metadata, requires_approval=requires_approval, functions=functions),
        status=status,
        details=_details(metadata),
        code=code,
        code_label=code_label,
        requires_approval=requires_approval,
        approval_type=source.approval_type if source is not None else None,
        availability=availability(entry_type, status),
        functions=functions,
        metadata=metadata,
        source=source,
    )


def meta_line(  # noqa: C901, PLR0912  (one case per entry type)
    entry_type: EntryType,
    metadata: Mapping[str, Any],
    *,
    requires_approval: bool = False,
    functions: Sequence[Function] = (),
) -> str:
    parts: list[str] = []
    class_path = str(metadata.get("class_path") or "")
    short = class_path.rsplit(".", 1)[-1] if class_path else ""
    match entry_type:
        case "tool":
            if metadata.get("is_toolkit"):
                parts = [class_path, f"{len(functions)} function{'s' if len(functions) != 1 else ''}"]
            else:
                module, qualname = metadata.get("module"), metadata.get("qualname")
                parts = [f"{module}.{qualname}" if module and qualname else class_path]
            if requires_approval:
                parts.append("@approval")
        case "model":
            parts = [f"provider {metadata.get('provider') or '?'}", f"model_id {metadata.get('model_id') or '?'}"]
        case "db":
            parts = [short, f"db_id {metadata.get('db_id') or '?'}"]
        case "vector_db":
            target = metadata.get("table_name") or metadata.get("collection")
            parts = [short, f"table_name {target}" if target else ""]
        case "schema":
            schema = cast("dict[str, Any]", metadata.get("schema") or metadata.get("schema_") or {})
            count = len(cast("dict[str, Any]", schema.get("properties") or {}))
            parts = ["BaseModel", f"{count} field{'s' if count != 1 else ''}"]
        case "function":
            parts = [str(metadata.get("signature") or class_path)]
        case "knowledge":
            parts = [
                str(metadata.get("vector_db_class") or ""),
                str(metadata.get("contents_db_class") or ""),
                f"max_results {metadata['max_results']}" if metadata.get("max_results") is not None else "",
            ]
        case "memory_manager" | "session_summary_manager":
            parts = [str(metadata.get("model_id") or short)]
        case "agent" | "team" | "workflow":
            parts = [f"id {metadata.get('id') or '?'}", class_path]
        case "learning":
            parts = [short]
    return " · ".join(part for part in parts if part)


def availability(entry_type: EntryType, status: Status) -> Availability:
    if status == "discovered":
        return Availability(
            "unavailable",
            "Not available in Studio.",
            "AgentOS discovered it so a component defined in code can be rebuilt, but only tools passed to "
            "Registry(tools=[...]) can be added to new agents.",
        )
    if entry_type == "tool":
        return Availability(
            "available",
            "Available in Studio.",
            "Passed to Registry(tools=[...]), so builders can attach it.",
        )
    return Availability("registered", "Registered.", "Studio can select it when building agents, teams and workflows.")


def _functions(metadata: Mapping[str, Any]) -> list[Function]:
    items = cast("list[dict[str, Any]]", metadata.get("functions") or [])
    return [
        Function(
            name=str(item.get("name") or ""),
            description=item.get("description"),
            parameters=item.get("parameters"),
            signature=item.get("signature"),
            requires_confirmation=bool(item.get("requires_confirmation")),
            external_execution=bool(item.get("external_execution")),
        )
        for item in items
    ]


def _details(metadata: Mapping[str, Any]) -> list[tuple[str, str]]:
    details = [(key, str(metadata[key])) for key in DETAIL_KEYS if metadata.get(key) not in {None, ""}]
    flags = [flag for flag in ("requires_confirmation", "external_execution") if metadata.get(flag)]
    if flags:
        details.append(("flags", ", ".join(flags)))
    functions = cast("list[dict[str, Any]]", metadata.get("functions") or [])
    if functions:
        details.append(("functions", ", ".join(str(item.get("name")) for item in functions)))
    return details


def _code(entry_type: EntryType, metadata: Mapping[str, Any]) -> tuple[str | None, str | None]:
    if entry_type == "schema":
        schema = metadata.get("schema") or metadata.get("schema_")
        return (json.dumps(schema, indent=2), "JSON schema") if schema else (None, None)
    parameters = metadata.get("parameters")
    if parameters:
        return json.dumps(parameters, indent=2), "parameters"
    return None, None


def tool_entry(entry: RegistryEntry, function: str | None = None) -> list[dict[str, Any]]:
    """The tool dicts a config stores for a registry tool (one per function of a toolkit).

    AgentOS rebuilds tools from ``parameters``, so the full function description is written, as ``to_dict()`` does.
    """
    if entry.functions:
        chosen = [item for item in entry.functions if function is None or item.name == function]
        return [
            _without_none(
                {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters or {"type": "object", "properties": {}, "required": []},
                    "requires_confirmation": item.requires_confirmation or None,
                    "external_execution": item.external_execution or None,
                    "toolkit": entry.name,
                }
            )
            for item in chosen
        ]
    return [
        _without_none(
            {
                "name": entry.name,
                "description": entry.description,
                "parameters": entry.metadata.get("parameters") or {"type": "object", "properties": {}, "required": []},
                "requires_confirmation": True if entry.requires_approval else None,
                "external_execution": entry.metadata.get("external_execution") or None,
                "approval_type": entry.approval_type,
            }
        )
    ]


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
