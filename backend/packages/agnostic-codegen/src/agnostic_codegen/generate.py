"""Config → deterministic, idiomatic Python: one module-level ``Agent(...)`` or ``Team(...)``.

Registry objects are referenced through the convention's namespaces (``tools.refund_customer``), members through
the component modules, and everything else as literals. The output is already in ruff's style (one argument per line,
trailing commas), so formatting it changes nothing a reader relies on.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from agnostic_codegen.convention import RegistryConvention, snake
from agnostic_spec.v3_1 import ComponentConfig, Kind, ModelRef, RefType, SharedConfig, TeamConfig, ToolRef, layout
from agnostic_spec.v3_1.refs import learning_name, schema_name
from agnostic_spec.v3_1.refs_index import MODEL_FIELDS

INDENT = "    "
CLASSES: Mapping[Kind, tuple[str, str]] = {"agent": ("agno.agent", "Agent"), "team": ("agno.team", "Team")}


@dataclass(frozen=True, slots=True)
class Note:
    """Something the reader should know about one field of the generated code."""

    path: str
    kind: str
    message: str


@dataclass(slots=True)
class Generated:
    code: str
    variable: str
    element_paths: dict[str, list[list[str]]] = field(default_factory=dict)
    """For list fields: config paths behind each emitted element (a toolkit stands for several functions)."""
    notes: list[Note] = field(default_factory=list)


class _Code:
    """An expression already rendered, emitted as is."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


@dataclass(slots=True)
class _Imports:
    modules: dict[str, set[str]] = field(default_factory=dict)

    def add(self, module: str, name: str) -> None:
        self.modules.setdefault(module, set()).add(name)

    def render(self) -> str:
        agno = sorted(module for module in self.modules if module == "agno" or module.startswith("agno."))
        local = sorted(module for module in self.modules if module not in agno)
        blocks = [
            [f"from {module} import {', '.join(sorted(self.modules[module]))}" for module in group]
            for group in (agno, local)
            if group
        ]
        return "\n\n".join("\n".join(block) for block in blocks)


def generate(config: ComponentConfig, convention: RegistryConvention | None = None) -> Generated:
    convention = convention or RegistryConvention()
    kind = config.kind
    module, cls = CLASSES[kind]
    imports = _Imports()
    imports.add(module, cls)
    data = config.dump()
    variable = snake(str(data.get("id") or data.get("name") or kind))
    generated = Generated(code="", variable=variable)

    arguments: list[tuple[str, object]] = []
    for name in _ordered(kind, data):
        value = _value(name, data[name], config, convention, imports, generated)
        arguments.append((name, value))

    lines = [f"{variable} = {cls}("]
    lines.extend(f"{INDENT}{name}={_render(value, 1)}," for name, value in arguments)
    lines.append(")")
    generated.code = f"{imports.render()}\n\n{'\n'.join(lines)}\n"
    return generated


def _ordered(kind: Kind, data: Mapping[str, Any]) -> list[str]:
    known = ["id", "name"]
    for section in layout(kind):
        known.extend(name for name in section["fields"] if name not in known)
    ordered = [name for name in known if name in data]
    ordered.extend(sorted(name for name in data if name not in ordered))
    return ordered


def _value(
    name: str,
    value: Any,  # noqa: ANN401
    config: ComponentConfig,
    convention: RegistryConvention,
    imports: _Imports,
    generated: Generated,
) -> object:
    def ref(ref_type: RefType, entry: str) -> _Code:
        namespace = convention.namespace(ref_type)
        imports.add(convention.registry_module, namespace)
        return _Code(f"{namespace}.{convention.attribute(ref_type, entry)}")

    reference = _registry(name, value, config, ref, generated)
    if reference is not None:
        return reference
    if name == "mode" and isinstance(config, TeamConfig) and isinstance(value, str):
        imports.add("agno.team.mode", "TeamMode")
        return _Code(f"TeamMode.{value}")
    if name == "members" and isinstance(config, TeamConfig):
        members: list[object] = []
        paths: list[list[str]] = []
        for index, member in enumerate(config.members or []):
            target = convention.teams_module if member.type == "team" else convention.agents_module
            attribute = snake(member.component_id or f"member_{index}")
            imports.add(target, attribute)
            members.append(_Code(attribute))
            paths.append([f"members[{index}]"])
        generated.element_paths[name] = paths
        return members
    if name == "learning" and isinstance(config, SharedConfig) and isinstance(config.learning, dict):
        generated.notes.append(
            Note("learning", "inline", "An inline learning config is shown as a literal; define it in code to run it.")
        )
    if isinstance(value, list):
        count = len(value)  # pyright: ignore[reportUnknownArgumentType]
        generated.element_paths[name] = [[f"{name}[{index}]"] for index in range(count)]
    return cast("object", value)


RefMaker = Callable[[RefType, str], _Code]


def _registry(
    name: str,
    value: Any,  # noqa: ANN401
    config: ComponentConfig,
    ref: RefMaker,
    generated: Generated,
) -> object | None:
    if name in MODEL_FIELDS:
        model = ModelRef.parse(value)
        return None if model is None else ref("model", model.id)
    if not isinstance(config, SharedConfig):
        return None
    if name == "tools":
        return _tool_refs(config, ref, generated)
    target = _named_ref(name, config)
    return None if target is None else ref(*target)


def _named_ref(name: str, config: SharedConfig) -> tuple[RefType, str] | None:
    entry: tuple[RefType, str | None] | None = None
    if name == "knowledge":
        entry = ("knowledge", config.knowledge.name if config.knowledge else None)
    elif name in {"input_schema", "output_schema"}:
        entry = ("schema", schema_name(getattr(config, name)))
    elif name == "memory_manager":
        entry = ("memory_manager", config.memory_manager.registry_id if config.memory_manager else None)
    elif name == "learning":
        entry = ("learning", learning_name(config.learning))
    if entry is None or entry[1] is None:
        return None
    return entry[0], entry[1]


def _tool_refs(config: SharedConfig, ref: RefMaker, generated: Generated) -> list[object]:
    tools: list[object] = []
    paths: list[list[str]] = []
    toolkits: dict[str, int] = {}
    for index, tool in enumerate(config.tools or []):
        if not isinstance(tool, ToolRef):
            tools.append(tool)
            paths.append([f"tools[{index}]"])
            continue
        if tool.toolkit is not None and tool.toolkit in toolkits:
            paths[toolkits[tool.toolkit]].append(f"tools[{index}]")
            continue
        if tool.toolkit is not None:
            toolkits[tool.toolkit] = len(tools)
        tools.append(ref("tool", tool.registry_name))
        paths.append([f"tools[{index}]"])
        if tool.needs_approval:
            generated.notes.append(Note(f"tools[{index}]", "approval", tool.name))
    generated.element_paths["tools"] = paths
    return tools


def _render(value: object, depth: int) -> str:  # noqa: PLR0911
    if isinstance(value, _Code):
        return value.text
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    pad = INDENT * (depth + 1)
    close = INDENT * depth
    if isinstance(value, list | tuple):
        items: list[object] = list(value)  # pyright: ignore[reportUnknownArgumentType]
        if not items:
            return "[]"
        body = "".join(f"{pad}{_render(item, depth + 1)},\n" for item in items)
        return f"[\n{body}{close}]"
    if isinstance(value, dict):
        entries: dict[object, object] = dict(value)  # pyright: ignore[reportUnknownArgumentType]
        if not entries:
            return "{}"
        body = "".join(
            f"{pad}{_render(str(key), depth + 1)}: {_render(item, depth + 1)},\n" for key, item in entries.items()
        )
        return f"{{\n{body}{close}}}"
    return json.dumps(str(value), ensure_ascii=False)


__all__ = ["CLASSES", "Generated", "Note", "generate"]
