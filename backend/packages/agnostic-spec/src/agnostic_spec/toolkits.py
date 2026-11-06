"""The Agno toolkits a tool catalog entry may name: the control plane's copy of the bridge's list.

``toolkits.json`` is written by the bridge's ``scripts/dump_toolkits.py`` together with the bridge's own copy, and a
test keeps the two equal. The control plane reads it for its forms and checks; a runtime with a newer bridge reports
its own list (``GET /agnostic/v1/toolkits``), which wins when the two differ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast

type ParamType = Literal["str", "int", "float", "bool", "list", "dict", "choice", "json"]

__all__ = ["ParamSpec", "ParamType", "ToolkitList", "ToolkitSpec", "parse_toolkits", "toolkit_list"]


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    type: ParamType
    required: bool
    default: Any = None
    choices: tuple[Any, ...] = ()
    secret: bool = False
    """A credential: entries pass the name of an environment variable on the runtime, never the value."""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ToolkitSpec:
    key: str
    class_path: str
    label: str
    description: str
    category: str
    local: bool
    """Runs commands or touches the runtime's files (shell, python, files): privileged, opt-in per runtime."""
    extra: str | None
    params: tuple[ParamSpec, ...]

    def param(self, name: str) -> ParamSpec | None:
        return next((param for param in self.params if param.name == name), None)


@dataclass(frozen=True, slots=True)
class ToolkitList:
    agno_version: str
    toolkits: tuple[ToolkitSpec, ...]

    def get(self, key: str) -> ToolkitSpec | None:
        return next((toolkit for toolkit in self.toolkits if toolkit.key == key), None)


def _param(data: dict[str, Any]) -> ParamSpec:
    return ParamSpec(
        name=str(data["name"]),
        type=cast("ParamType", data.get("type") or "str"),
        required=bool(data.get("required")),
        default=data.get("default"),
        choices=tuple(cast("list[Any]", data.get("choices") or [])),
        secret=bool(data.get("secret")),
        description=str(data.get("description") or ""),
    )


def parse_toolkits(data: dict[str, Any]) -> ToolkitList:
    """A list in the bridge's format (the JSON file, or a runtime's ``GET /agnostic/v1/toolkits`` answer)."""
    items = cast("list[dict[str, Any]]", data.get("toolkits") or [])
    return ToolkitList(
        agno_version=str(data.get("agno_version") or ""),
        toolkits=tuple(
            ToolkitSpec(
                key=str(item["key"]),
                class_path=str(item["class_path"]),
                label=str(item.get("label") or item["key"]),
                description=str(item.get("description") or ""),
                category=str(item.get("category") or "other"),
                local=bool(item.get("local")),
                extra=item.get("extra"),
                params=tuple(_param(param) for param in cast("list[dict[str, Any]]", item.get("params") or [])),
            )
            for item in items
        ),
    )


@cache
def toolkit_list() -> ToolkitList:
    return parse_toolkits(json.loads(Path(__file__).with_name("toolkits.json").read_text(encoding="utf-8")))
