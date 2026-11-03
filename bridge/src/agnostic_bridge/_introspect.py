"""Where code-defined components and registry entries live in the AgentOS's source.

- ``GET /agnostic/v1/introspect/components``: the agents, teams and workflows defined in code on this AgentOS (not
  the db-stored ones ``/components`` lists), each with its serialized config and the module-level assignment that
  defines it. Studio shows them as read-only starting points.
- ``GET /agnostic/v1/registry/{type}/{name}/source``: the source of one registry entry (a tool's entrypoint
  function, a schema's class, a model's or manager's class…), whether Studio may build with it (``declared``: a tool
  found only on a registered component isn't), and the approval flags of a tool.

Locations come from ``inspect`` and are best-effort: ``module``, ``file`` and ``line`` are null when the source isn't
available (built in a function, a C extension, a zip import). Names are those ``GET /registry`` lists. Needs
``components:read`` and ``registry:read`` respectively (:data:`~agnostic_bridge.SCOPE_MAPPINGS`).
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import tokenize
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal

from agno.agent import Agent
from agno.os.schema import RegistryResourceType
from agno.team import Team
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_warning
from agno.workflow import Workflow
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS
    from agno.registry import Registry

INTROSPECT_COMPONENTS_PATH = "/introspect/components"
REGISTRY_SOURCE_PATH = "/registry/{type}/{name}/source"

try:  # the built-in manager team and members: the registry never serves them, so neither does introspection
    from agno.registry._reserved import is_framework_owned
except ImportError:  # private in agno

    def is_framework_owned(component: Any) -> bool:
        return False


class SourceLocation(BaseModel):
    module: str | None = Field(None, description="Dotted module name")
    file: str | None = Field(None, description="Absolute path of the source file")
    line: int | None = Field(None, description="1-based line of the definition")


class CodeComponent(SourceLocation):
    id: str | None = None
    kind: Literal["agent", "team", "workflow"]
    name: str | None = None
    config: dict[str, Any] | None = Field(description="to_dict() of the component; null when it can't serialize")


class RegistrySource(SourceLocation):
    type: RegistryResourceType
    name: str
    declared: bool = Field(description="Studio may build with it; false for a tool only found on a component")
    requires_confirmation: bool = Field(description="A tool call pauses for a human first")
    approval_type: str | None = Field(None, description="'required' or 'audit' for a tool under @approval")


@lru_cache(maxsize=256)
def _top_level_assignments(file: str, mtime: float) -> dict[str, int]:
    """``name → line`` of the module-level assignments in ``file`` (``mtime`` keys the cache)."""
    try:
        with tokenize.open(file) as source:
            tree = ast.parse(source.read(), filename=file)
    except (OSError, SyntaxError, ValueError):
        return {}
    lines: dict[str, int] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                lines.setdefault(target.id, node.lineno)
    return lines


def assignment_of(obj: Any) -> SourceLocation:
    """The module-level ``name = …`` that binds ``obj``, among the loaded modules.

    A module that imports the object binds it too, so only a module whose source assigns the name counts."""
    for module_name, module in list(sys.modules.items()):
        namespace = getattr(module, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        names = [name for name, value in list(namespace.items()) if value is obj]
        file = getattr(module, "__file__", None)
        if not names or not isinstance(file, str) or not file.endswith(".py"):
            continue
        try:
            mtime = os.path.getmtime(file)
        except OSError:
            continue
        assignments = _top_level_assignments(file, mtime)
        lines = [assignments[name] for name in names if name in assignments]
        if lines:
            return SourceLocation(module=module_name, file=os.path.abspath(file), line=min(lines))
    return SourceLocation()


def definition_of(target: Any) -> SourceLocation:
    """Where a function or class is defined."""
    target = inspect.unwrap(target) if callable(target) else target
    target = getattr(target, "__func__", target)  # bound method → function
    module = getattr(target, "__module__", None)
    try:
        file = inspect.getsourcefile(target)
    except TypeError:
        file = None
    line: int | None = None
    if file is not None:
        try:
            line = inspect.getsourcelines(target)[1] or None
        except (OSError, TypeError):
            line = None
    return SourceLocation(
        module=module if isinstance(module, str) else None,
        file=os.path.abspath(file) if file else None,
        line=line,
    )


def code_components(agent_os: AgentOS) -> list[CodeComponent]:
    found: list[CodeComponent] = []
    groups: tuple[tuple[Literal["agent", "team", "workflow"], list[Any] | None, type], ...] = (
        ("agent", agent_os.agents, Agent),
        ("team", agent_os.teams, Team),
        ("workflow", agent_os.workflows, Workflow),
    )
    for kind, components, cls in groups:
        for component in components or []:
            if not isinstance(component, cls) or is_framework_owned(component):
                continue  # remote agents and factories have no config here
            try:
                config: dict[str, Any] | None = component.to_dict()
            except Exception as e:
                log_warning(f"Could not serialize {kind} {getattr(component, 'id', None)}: {e}")
                config = None
            found.append(
                CodeComponent(
                    id=getattr(component, "id", None),
                    kind=kind,
                    name=getattr(component, "name", None),
                    config=config,
                    **assignment_of(component).model_dump(),
                )
            )
    return found


def _named(entry: Any, *attributes: str) -> set[str]:
    names = {getattr(entry, attribute, None) for attribute in attributes}
    return {name for name in names if isinstance(name, str) and name}


def _tool_flags(function: Function, toolkit: Toolkit | None = None) -> tuple[bool, str | None]:
    listed = toolkit is not None and function.name in (toolkit.requires_confirmation_tools or [])
    return bool(function.requires_confirmation) or listed, function.approval_type


def _tool_source(registry: Registry, name: str) -> RegistrySource | None:
    def source(target: Any, declared_as: str, flags: tuple[bool, str | None]) -> RegistrySource:
        return RegistrySource(
            type=RegistryResourceType.TOOL,
            name=name,
            declared=registry.tool_is_declared(declared_as),
            requires_confirmation=flags[0],
            approval_type=flags[1],
            **definition_of(target).model_dump(),
        )

    for tool in registry.tools or []:
        if isinstance(tool, Toolkit):
            if name in _named(tool, "name"):
                functions = list((tool.functions or {}).values())
                requires = any(_tool_flags(function, tool)[0] for function in functions)
                approval = next((function.approval_type for function in functions if function.approval_type), None)
                return source(type(tool), name, (requires, approval))
        elif isinstance(tool, Function):
            if name in _named(tool, "name"):
                return source(tool.entrypoint or type(tool), name, _tool_flags(tool))
        elif callable(tool) and name in _named(tool, "__name__"):
            return source(tool, name, (False, None))
    # A function of a registered toolkit: the toolkit is what was declared.
    for tool in registry.tools or []:
        if isinstance(tool, Toolkit) and (function := (tool.functions or {}).get(name)) is not None:
            toolkit_name = getattr(tool, "name", None) or type(tool).__name__
            return source(function.entrypoint or type(tool), toolkit_name, _tool_flags(function, tool))
    return None


# Registry list and the attributes GET /registry names its entries by, per type (tools are handled apart).
_ENTRIES: dict[RegistryResourceType, tuple[str, tuple[str, ...]]] = {
    RegistryResourceType.MODEL: ("models", ("id", "name")),
    RegistryResourceType.DB: ("dbs", ("name", "id")),
    RegistryResourceType.VECTOR_DB: ("vector_dbs", ("name", "id", "collection", "table_name")),
    RegistryResourceType.SCHEMA: ("schemas", ("__name__",)),
    RegistryResourceType.FUNCTION: ("functions", ("__name__",)),
    RegistryResourceType.AGENT: ("agents", ("id", "name")),
    RegistryResourceType.TEAM: ("teams", ("id", "name")),
    RegistryResourceType.WORKFLOW: ("workflows", ("id", "name")),
    RegistryResourceType.KNOWLEDGE: ("knowledge", ("name",)),
    RegistryResourceType.MEMORY_MANAGER: ("memory_managers", ("name", "id")),
    RegistryResourceType.SESSION_SUMMARY_MANAGER: ("session_summary_managers", ("name", "id")),
    RegistryResourceType.LEARNING: ("learning", ("name",)),
}
# Defined by a class or function themselves; every other entry is an instance, located by its class.
_DEFINITIONS = {RegistryResourceType.SCHEMA, RegistryResourceType.FUNCTION}
_COMPONENTS = {RegistryResourceType.AGENT, RegistryResourceType.TEAM, RegistryResourceType.WORKFLOW}


def registry_source(registry: Registry, resource_type: RegistryResourceType, name: str) -> RegistrySource | None:
    if resource_type == RegistryResourceType.TOOL:
        return _tool_source(registry, name)
    attribute, name_attributes = _ENTRIES[resource_type]
    for entry in getattr(registry, attribute, None) or []:
        names = _named(entry, *name_attributes) or {type(entry).__name__}
        if name not in names:
            continue
        if resource_type in _DEFINITIONS:
            location = definition_of(entry)
        elif resource_type in _COMPONENTS:
            location = assignment_of(entry)
            if location.file is None:
                location = definition_of(type(entry))
        else:
            location = definition_of(type(entry))
        return RegistrySource(
            type=resource_type,
            name=name,
            declared=True,
            requires_confirmation=False,
            approval_type=None,
            **location.model_dump(),
        )
    return None


def add_introspect_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.get(
        INTROSPECT_COMPONENTS_PATH,
        operation_id="agnostic_bridge_list_code_components",
        summary="List code-defined components",
        description=(
            "The agents, teams and workflows defined in code on this AgentOS (not db-stored components), with their "
            "serialized config and where they are assigned in the source. Needs components:read."
        ),
        response_model=list[CodeComponent],
    )
    async def list_code_components() -> list[CodeComponent]:
        return code_components(agent_os)

    @router.get(
        REGISTRY_SOURCE_PATH,
        operation_id="agnostic_bridge_get_registry_source",
        summary="Get the source of a registry entry",
        description=(
            "Where a registry entry is defined, whether Studio may build with it, and a tool's approval flags. "
            "Names are those GET /registry lists. Needs registry:read."
        ),
        response_model=RegistrySource,
        responses={404: {"description": "No such entry in the registry"}},
    )
    async def get_registry_source(type: RegistryResourceType, name: str) -> RegistrySource:
        registry = agent_os.registry
        found = registry_source(registry, type, name) if registry is not None else None
        if found is None:
            raise HTTPException(status_code=404, detail=f"No {type.value} named {name!r} in the registry")
        return found
