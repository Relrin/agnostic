"""Component configs as agno 3.1 writes them (``Agent.to_dict()`` / ``Team.to_dict()``)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agnostic_spec.diagnostics import Diagnostic
from agnostic_spec.fields import field_meta
from agnostic_spec.v3_1.agent import AgentConfig
from agnostic_spec.v3_1.base import ComponentConfig, Kind, SharedConfig
from agnostic_spec.v3_1.refs import KnowledgeRef, MemberRef, MemoryManagerRef, ModelRef, ToolRef
from agnostic_spec.v3_1.refs_index import RefType, RefUse, iter_refs
from agnostic_spec.v3_1.rules import check
from agnostic_spec.v3_1.team import TEAM_MODES, TeamConfig, TeamMode

AGNO_MINOR = "3.1"

MODELS: dict[Kind, type[ComponentConfig]] = {"agent": AgentConfig, "team": TeamConfig}

SECTIONS: dict[Kind, tuple[tuple[str, str], ...]] = {
    "agent": (
        ("identity", "Identity"),
        ("model", "Model"),
        ("instructions", "Instructions"),
        ("tools", "Tools"),
        ("knowledge", "Knowledge"),
        ("memory", "Memory"),
        ("context", "Context"),
        ("output", "Output schema"),
        ("session_state", "Session state"),
        ("advanced", "Advanced"),
    ),
    "team": (
        ("team", "How the team works together"),
        ("members", "Members"),
        ("identity", "Identity"),
        ("model", "Leader model"),
        ("instructions", "Leader instructions"),
        ("tools", "Tools"),
        ("memory", "Memory"),
        ("knowledge", "Knowledge"),
        ("context", "Context"),
        ("output", "Output schema"),
        ("session_state", "Session state"),
        ("advanced", "Advanced"),
    ),
}


def parse(kind: Kind, data: dict[str, Any]) -> ComponentConfig:
    """Raises :class:`pydantic.ValidationError` when the shape is wrong."""
    return MODELS[kind].parse(data)


def shape_errors(kind: Kind, data: dict[str, Any]) -> list[Diagnostic]:
    """Shape problems as diagnostics (empty when the document parses)."""
    try:
        parse(kind, data)
    except ValidationError as exc:
        return [
            Diagnostic(_path(error["loc"]), "error", f"shape.{error['type']}", error["msg"])
            for error in exc.errors(include_url=False)
        ]
    return []


def layout(kind: Kind) -> list[dict[str, Any]]:
    """Sections in display order with their fields (by ``order``); fields without metadata are left to Advanced."""
    model = MODELS[kind]
    by_section: dict[str, list[tuple[int, str]]] = {}
    for name in model.model_fields:
        meta = field_meta(model, name)
        if meta is not None:
            by_section.setdefault(meta.section, []).append((meta.order, name))
    return [
        {"id": section, "label": label, "fields": [name for _, name in sorted(by_section.get(section, []))]}
        for section, label in SECTIONS[kind]
    ]


def json_schema(kind: Kind) -> dict[str, Any]:
    schema = MODELS[kind].model_json_schema(mode="validation")
    schema["x-agnostic-sections"] = layout(kind)
    schema["x-agnostic-agno"] = AGNO_MINOR
    return schema


def _path(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        elif not path:
            path = part
        elif part.startswith(("ToolRef", "dict[", "list[", "str", "int", "bool", "ModelRef", "function-")):
            # Union branch names pydantic puts in the location; they are not fields.
            continue
        else:
            path += f".{part}"
    return path


__all__ = [
    "AGNO_MINOR",
    "MODELS",
    "SECTIONS",
    "TEAM_MODES",
    "AgentConfig",
    "ComponentConfig",
    "Kind",
    "KnowledgeRef",
    "MemberRef",
    "MemoryManagerRef",
    "ModelRef",
    "RefType",
    "RefUse",
    "SharedConfig",
    "TeamConfig",
    "TeamMode",
    "ToolRef",
    "check",
    "iter_refs",
    "json_schema",
    "layout",
    "parse",
    "shape_errors",
]
