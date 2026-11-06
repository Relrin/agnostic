"""The Agno toolkits a tool catalog entry may name, and how the bridge builds one.

The list (``toolkits.json``) is generated from agno's sources by ``scripts/dump_toolkits.py``. A catalog entry names
a toolkit by its ``key``; the bridge imports only the ``class_path`` this list holds for that key, never a path that
came over the network, and passes only the parameters the list declares.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

ParamType = Literal["str", "int", "float", "bool", "list", "dict", "choice", "json"]


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: ParamType
    required: bool
    default: Any = None
    choices: tuple[Any, ...] = ()
    secret: bool = False
    """Credentials: a catalog entry passes them as the name of an environment variable, never as a value."""
    description: str = ""


@dataclass(frozen=True)
class ToolkitSpec:
    key: str
    class_path: str
    """``module:Class`` under ``agno.tools``."""
    label: str
    description: str
    category: str
    local: bool
    """Runs commands or touches the runtime's files: built only on runtimes that opt in."""
    extra: str | None
    """The package its ImportError asks for, when it needs one."""
    params: tuple[ParamSpec, ...]

    def param(self, name: str) -> ParamSpec | None:
        return next((param for param in self.params if param.name == name), None)


@dataclass(frozen=True)
class ToolkitList:
    agno_version: str
    toolkits: tuple[ToolkitSpec, ...]

    def get(self, key: str) -> ToolkitSpec | None:
        return next((toolkit for toolkit in self.toolkits if toolkit.key == key), None)


def _spec(data: dict[str, Any]) -> ToolkitSpec:
    return ToolkitSpec(
        key=data["key"],
        class_path=data["class_path"],
        label=data["label"],
        description=data.get("description", ""),
        category=data.get("category", "other"),
        local=bool(data.get("local")),
        extra=data.get("extra"),
        params=tuple(
            ParamSpec(
                name=param["name"],
                type=param["type"],
                required=bool(param["required"]),
                default=param.get("default"),
                choices=tuple(param.get("choices") or ()),
                secret=bool(param.get("secret")),
                description=param.get("description", ""),
            )
            for param in data.get("params", [])
        ),
    )


@cache
def toolkit_list() -> ToolkitList:
    data = json.loads(Path(__file__).with_name("toolkits.json").read_text(encoding="utf-8"))
    return ToolkitList(agno_version=data["agno_version"], toolkits=tuple(_spec(item) for item in data["toolkits"]))


def load_class(spec: ToolkitSpec) -> type:
    """Import the toolkit class; raises ImportError when its package isn't installed on this runtime."""
    module_name, _, class_name = spec.class_path.partition(":")
    if not module_name.startswith("agno.tools."):
        raise ImportError(f"{spec.class_path} is not an agno toolkit")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


@cache
def importable(key: str) -> bool:
    """Whether this runtime can build the toolkit (its optional package is installed)."""
    spec = toolkit_list().get(key)
    if spec is None:
        return False
    try:
        _ = load_class(spec)
    except Exception:  # an optional package missing, or one that fails to import here
        return False
    return True
