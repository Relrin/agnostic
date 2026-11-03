"""How generated code reaches registry objects. Repositories differ, so every part is configurable."""

from __future__ import annotations

import keyword
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from agnostic_spec.v3_1 import RefType

DEFAULT_NAMESPACES: Mapping[RefType, str] = {
    "tool": "tools",
    "model": "models",
    "knowledge": "knowledge",
    "schema": "schemas",
    "memory_manager": "memory",
    "learning": "learning",
}

_NOT_IDENT = re.compile(r"[^0-9a-zA-Z_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake(name: str) -> str:
    """``"support-triage"`` → ``support_triage``; ``"claude-opus-5.5"`` → ``claude_opus_5_5``."""
    value = _NOT_IDENT.sub("_", _CAMEL.sub("_", name)).strip("_").lower() or "component"
    if value[0].isdigit():
        value = f"_{value}"
    return f"{value}_" if keyword.iskeyword(value) else value


@dataclass(frozen=True, slots=True)
class RegistryConvention:
    registry_module: str = "app.registry"
    namespaces: Mapping[RefType, str] = field(default_factory=lambda: dict(DEFAULT_NAMESPACES))
    agents_module: str = "app.agents"
    teams_module: str = "app.teams"
    workflows_module: str = "app.workflows"
    functions_module: str = "app.functions"
    """Where the registered step functions, evaluators and selectors are imported from."""
    keep_schema_names: bool = True
    """Schemas are classes: keep ``TriageResult`` as is instead of snake-casing it."""

    @property
    def first_party(self) -> tuple[str, ...]:
        modules = (
            self.registry_module,
            self.agents_module,
            self.teams_module,
            self.workflows_module,
            self.functions_module,
        )
        return tuple(sorted({module.split(".", 1)[0] for module in modules}))

    def namespace(self, ref_type: RefType) -> str:
        return self.namespaces.get(ref_type, DEFAULT_NAMESPACES.get(ref_type, "registry"))

    def component_module(self, ref_type: RefType) -> str:
        """The module a step or member executor of ``ref_type`` is imported from."""
        modules: dict[RefType, str] = {
            "agent": self.agents_module,
            "team": self.teams_module,
            "workflow": self.workflows_module,
            "function": self.functions_module,
        }
        return modules[ref_type]

    def attribute(self, ref_type: RefType, name: str) -> str:
        if ref_type == "schema" and self.keep_schema_names and name.isidentifier():
            return name
        if ref_type == "function" and name.isidentifier():
            return name
        return snake(name)
