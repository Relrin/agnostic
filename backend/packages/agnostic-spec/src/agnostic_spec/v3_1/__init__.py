"""Component configs as agno 3.1 writes them (``Agent.to_dict()`` / ``Team.to_dict()`` / ``Workflow.to_dict()``)."""

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
from agnostic_spec.v3_1.workflow import (
    HUMAN_REVIEW_SUPPORT,
    NODE_MODELS,
    REVIEW_GROUPS,
    HumanReview,
    Node,
    NodeInfo,
    StepNode,
    WorkflowConfig,
    iter_nodes,
    looks_like_cel,
    step_count,
)

AGNO_MINOR = "3.1"

MODELS: dict[Kind, type[ComponentConfig]] = {"agent": AgentConfig, "team": TeamConfig, "workflow": WorkflowConfig}

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
    "workflow": (
        ("identity", "Identity"),
        ("input", "Input and state"),
        ("history", "History"),
        ("advanced", "Advanced"),
    ),
}
NODE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("settings", "Settings"),
    ("executor", "Executor"),
    ("history", "History"),
    ("review", "Human review"),
)


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


def node_layout(node_type: str) -> list[dict[str, Any]]:
    """The inspector's sections for one node type; ``steps`` (the children) are edited on the canvas."""
    model = NODE_MODELS[node_type]
    by_section: dict[str, list[tuple[int, str]]] = {}
    for name in model.model_fields:
        meta = field_meta(model, name)
        if meta is not None and meta.section != "steps":
            by_section.setdefault(meta.section, []).append((meta.order, name))
    return [
        {"id": section, "label": label, "fields": [name for _, name in sorted(by_section[section])]}
        for section, label in NODE_SECTIONS
        if section in by_section
    ]


def json_schema(kind: Kind) -> dict[str, Any]:
    schema = MODELS[kind].model_json_schema(mode="validation")
    schema["x-agnostic-sections"] = layout(kind)
    schema["x-agnostic-agno"] = AGNO_MINOR
    if kind == "workflow":
        schema["x-agnostic-nodes"] = {node_type: node_layout(node_type) for node_type in NODE_MODELS}
        schema["x-agnostic-human-review"] = {
            "groups": {group: list(fields) for group, fields in REVIEW_GROUPS.items()},
            "support": {node_type: list(groups) for node_type, groups in HUMAN_REVIEW_SUPPORT.items()},
        }
    return schema


def _path(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        elif not path:
            path = part
        elif (
            part.startswith(("ToolRef", "dict[", "list[", "str", "int", "bool", "ModelRef", "function-"))
            or part in NODE_MODELS
        ):
            # Union branch names pydantic puts in the location; they are not fields.
            continue
        else:
            path += f".{part}"
    return path


__all__ = [
    "AGNO_MINOR",
    "HUMAN_REVIEW_SUPPORT",
    "MODELS",
    "NODE_MODELS",
    "REVIEW_GROUPS",
    "SECTIONS",
    "TEAM_MODES",
    "AgentConfig",
    "ComponentConfig",
    "HumanReview",
    "Kind",
    "KnowledgeRef",
    "MemberRef",
    "MemoryManagerRef",
    "ModelRef",
    "Node",
    "NodeInfo",
    "RefType",
    "RefUse",
    "SharedConfig",
    "StepNode",
    "TeamConfig",
    "TeamMode",
    "ToolRef",
    "WorkflowConfig",
    "check",
    "iter_nodes",
    "iter_refs",
    "json_schema",
    "layout",
    "looks_like_cel",
    "node_layout",
    "parse",
    "shape_errors",
    "step_count",
]
