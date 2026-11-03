"""Python → config: read the ``Agent``/``Team``/``Workflow(...)`` a module binds to a name back into its config.

Only literals and references the convention knows become config: registry attributes (``tools.refund_customer``,
however the registry module was imported), imported components and functions, ``TeamMode.x``, ``HumanReview(...)``
and the workflow primitives, plus simple module-level names (``investigate = Parallel(...)``, a selector constant
built from implicitly concatenated strings). Anything else is reported where it is and its field becomes
**code-owned**: the config leaves it out, the form shows it read-only, and nothing in the code is ever dropped.
Nothing is imported or executed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

import libcst as cst
from libcst.helpers import get_full_name_for_node
from libcst.metadata import CodeRange, MetadataWrapper, PositionProvider

from agnostic_codegen.convention import DEFAULT_NAMESPACES, RegistryConvention
from agnostic_codegen.spans import Span
from agnostic_spec.v3_1 import ComponentConfig, Kind, RefType, iter_refs, parse, shape_errors
from agnostic_spec.v3_1.refs_index import MODEL_FIELDS

Severity = Literal["error", "warning", "info"]
MAX_SOURCE_BYTES = 256_000
MAX_RESOLVE_DEPTH = 32

COMPONENT_CLASSES: Mapping[str, Kind] = {"Agent": "agent", "Team": "team", "Workflow": "workflow"}
NODE_CLASSES = frozenset({"Step", "Steps", "Parallel", "Condition", "Loop", "Router"})
# Positional parameters of each class, in agno's order.
POSITIONAL: Mapping[str, tuple[str, ...]] = {
    "Step": ("name", "agent", "team", "executor", "workflow", "step_id", "description"),
    "Steps": ("name", "description", "steps"),
    "Condition": ("steps", "evaluator", "else_steps", "name", "description"),
    "Loop": ("steps", "name", "description", "max_iterations", "end_condition"),
    "Router": ("choices", "selector", "name", "description"),
}
STEP_EXECUTORS: Mapping[str, tuple[str, RefType]] = {
    "agent": ("agent_id", "agent"),
    "team": ("team_id", "team"),
    "workflow": ("workflow_id", "workflow"),
    "executor": ("executor_ref", "function"),
}
CALLABLES: Mapping[str, Mapping[str, str]] = {
    "Condition": {"evaluator": "evaluator_type"},
    "Loop": {"end_condition": "end_condition_type"},
    "Router": {"selector": "selector_type"},
}
LANES: Mapping[str, tuple[str, ...]] = {
    "Steps": ("steps",),
    "Parallel": ("steps",),
    "Condition": ("steps", "else_steps"),
    "Loop": ("steps",),
    "Router": ("choices",),
}
REF_FIELDS: Mapping[str, RefType] = {
    **dict.fromkeys(MODEL_FIELDS, "model"),
    "knowledge": "knowledge",
    "memory_manager": "memory_manager",
    "learning": "learning",
}
# Constructor arguments a stored component can't hold, with what to do about them.
CODE_ONLY: Mapping[str, str] = {
    "pre_hooks": (
        "`pre_hooks` can't be stored in a Studio component; keep this agent code-backed or move the hook into a "
        "registered tool."
    ),
    "post_hooks": (
        "`post_hooks` can't be stored in a Studio component; keep this agent code-backed or move the hook into a "
        "registered tool."
    ),
    "tool_hooks": "`tool_hooks` can't be stored in a Studio component; keep this component code-backed.",
    "fallback_models": "Fallback models can't be stored in a Studio component; register a model preset instead.",
    "skills": "Skills can't be stored in a Studio component; keep this component code-backed.",
    "compression_manager": "A compression manager can't be stored in a Studio component.",
    "session_summary_manager": "A session summary manager can't be stored in a Studio component.",
    "knowledge_retriever": "A knowledge retriever is code; register a knowledge base and name it instead.",
    "additional_input": "`additional_input` can't be stored in a Studio component.",
    "media_storage": "Media storage comes from the AgentOS, not from a Studio component.",
    "db": "The database comes from the AgentOS; a Studio component doesn't name one.",
    "agent": "A workflow agent can't be stored in a Studio component; keep this workflow code-backed.",
    "events_to_skip": "`events_to_skip` can't be stored in a Studio component.",
}


@dataclass(frozen=True, slots=True)
class CodeDiagnostic:
    severity: Severity
    code: str
    message: str
    line: int
    column: int
    end_line: int
    end_column: int
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
            "path": self.path,
        }


class Resolver(Protocol):
    def resolve(self, ref_type: RefType, attribute: str) -> object | None:
        """The config value for a reference, by its attribute name in code (``refund_customer``).

        Tools answer a list (a toolkit stands for its functions), models a ``ModelRef`` dict, knowledge, memory
        managers and learning machines their stored dict, schemas their class name, components their id and
        functions their name. ``None`` when the instance doesn't have it.
        """
        ...


@dataclass(slots=True)
class Lookup:
    """A :class:`Resolver` from known entries, keyed by the attribute name the convention gives them."""

    convention: RegistryConvention = field(default_factory=RegistryConvention)
    entries: dict[tuple[str, str], object] = field(default_factory=dict[tuple[str, str], object])

    def add(self, ref_type: RefType, name: str, value: object) -> None:
        key = (ref_type, self.convention.attribute(ref_type, name))
        if ref_type == "tool":
            tools = cast("list[object]", self.entries.setdefault(key, []))
            if value not in tools:
                tools.append(value)
        else:
            self.entries.setdefault(key, value)

    def resolve(self, ref_type: RefType, attribute: str) -> object | None:
        return self.entries.get((ref_type, attribute))

    def learn(self, configs: Iterable[ComponentConfig]) -> Lookup:
        """Add every reference these configs make, with the value they store for it."""
        for config in configs:
            data = config.dump()
            for use in iter_refs(config):
                self._learn(use.type, use.name, use.path, data)
        return self

    def _learn(self, ref_type: RefType, name: str, path: str, data: Mapping[str, Any]) -> None:
        if ref_type in {"agent", "team", "workflow", "function"} or ref_type == "schema":
            self.add(ref_type, name, name)
        else:
            value = _at(data, path)
            if value is not None:
                self.add(ref_type, name, value)


def _at(data: Mapping[str, Any], path: str) -> object | None:
    current: Any = data
    for part in path.replace("]", "").replace("[", ".").split("."):
        if isinstance(current, list):
            items: list[Any] = current  # pyright: ignore[reportUnknownVariableType]
            current = items[int(part)] if part.isdigit() and int(part) < len(items) else None
        elif isinstance(current, Mapping):
            current = cast("Mapping[str, Any]", current).get(part)
        else:
            return None
    return cast("object", current)


@dataclass(slots=True)
class Parsed:
    kind: Kind | None
    variable: str | None
    config: dict[str, Any] | None
    diagnostics: list[CodeDiagnostic] = field(default_factory=list[CodeDiagnostic])
    spans: dict[str, Span] = field(default_factory=dict[str, Span])
    code_owned: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return self.config is not None and not any(item.severity == "error" for item in self.diagnostics)


@dataclass(slots=True)
class Reading:
    """A parse with the syntax nodes behind each config path, for edits that keep the rest of the file."""

    parsed: Parsed
    module: cst.Module | None = None
    component: cst.Call | None = None
    calls: dict[str, cst.Call] = field(default_factory=dict[str, cst.Call])
    """Config path of a workflow node (``""`` for the component itself) → its constructor call."""
    args: dict[str, cst.Arg] = field(default_factory=dict[str, cst.Arg])
    """``path.keyword`` → the keyword argument that sets it."""
    elements: dict[str, list[cst.BaseElement]] = field(default_factory=dict[str, list[cst.BaseElement]])
    """``path.keyword`` of a list field → its elements, in order."""
    element_paths: dict[str, list[list[str]]] = field(default_factory=dict[str, list[list[str]]])
    """``path.keyword`` of a list field → the config paths behind each element (a toolkit stands for several)."""


class _Unsupported(Exception):  # noqa: N818
    def __init__(self, node: cst.CSTNode, message: str, code: str = "unsupported") -> None:
        super().__init__(message)
        self.node = node
        self.message = message
        self.code = code


def parse_source(
    code: str,
    *,
    kind: Kind | None = None,
    component_id: str | None = None,
    convention: RegistryConvention | None = None,
    resolver: Resolver | None = None,
) -> Parsed:
    return read_source(code, kind=kind, component_id=component_id, convention=convention, resolver=resolver).parsed


def read_source(
    code: str,
    *,
    kind: Kind | None = None,
    component_id: str | None = None,
    convention: RegistryConvention | None = None,
    resolver: Resolver | None = None,
) -> Reading:
    if len(code.encode()) > MAX_SOURCE_BYTES:
        message = f"The file is larger than {MAX_SOURCE_BYTES // 1000} kB."
        return Reading(Parsed(kind, None, None, [CodeDiagnostic("error", "too_large", message, 1, 0, 1, 0)]))
    try:
        module = cst.parse_module(code)
    except cst.ParserSyntaxError as exc:
        line, column = exc.editor_line, max(exc.editor_column - 1, 0)
        message = f"Syntax error: {exc.message}"
        return Reading(
            Parsed(kind, None, None, [CodeDiagnostic("error", "syntax", message, line, column, line, column)])
        )
    reader = _Reader(MetadataWrapper(module), convention or RegistryConvention(), resolver or Lookup())
    return reader.read(kind, component_id)


@dataclass(frozen=True, slots=True)
class Found:
    """A component a file defines: the module-level name, its kind and its ``id=`` (when it is a literal)."""

    variable: str
    kind: Kind
    component_id: str | None


def components_in(code: str) -> list[Found]:
    """Every component the file defines, without reading their settings (empty when the file doesn't parse)."""
    if len(code.encode()) > MAX_SOURCE_BYTES:
        return []
    try:
        module = cst.parse_module(code)
    except cst.ParserSyntaxError:
        return []
    reader = _Reader(MetadataWrapper(module), RegistryConvention(), Lookup())
    return [Found(name, kind, identifier) for name, _, kind, identifier in reader.candidates(None)]


@dataclass
class _Reader:
    wrapper: MetadataWrapper
    convention: RegistryConvention
    resolver: Resolver
    diagnostics: list[CodeDiagnostic] = field(default_factory=list[CodeDiagnostic])
    spans: dict[str, Span] = field(default_factory=dict[str, Span])
    code_owned: list[str] = field(default_factory=list[str])
    imports: dict[str, str] = field(default_factory=dict[str, str])
    assignments: dict[str, tuple[cst.CSTNode, cst.BaseExpression]] = field(
        default_factory=dict[str, tuple[cst.CSTNode, cst.BaseExpression]]
    )
    functions: set[str] = field(default_factory=set[str])
    resolving: list[str] = field(default_factory=list[str])

    def __post_init__(self) -> None:
        self.module = self.wrapper.module
        self.ranges: Mapping[cst.CSTNode, CodeRange] = self.wrapper.resolve(PositionProvider)
        self.lines = self.module.code.splitlines()
        self.reading = Reading(Parsed(None, None, None), module=self.module)
        self._index()

    # ---------------------------------------------------------------- module index
    def _index(self) -> None:  # noqa: C901
        for statement in self.module.body:
            if isinstance(statement, cst.FunctionDef):
                self.functions.add(statement.name.value)
            if not isinstance(statement, cst.SimpleStatementLine):
                continue
            for small in statement.body:
                if isinstance(small, cst.ImportFrom):
                    self._import_from(small)
                elif isinstance(small, cst.Import):
                    for alias in small.names:
                        dotted = get_full_name_for_node(alias.name) or ""
                        if alias.asname is not None and isinstance(alias.asname.name, cst.Name):
                            self.imports[alias.asname.name.value] = dotted
                        else:
                            head = dotted.split(".", 1)[0]
                            self.imports[head] = head
                elif isinstance(small, cst.Assign) and len(small.targets) == 1:
                    target = small.targets[0].target
                    if isinstance(target, cst.Name):
                        self.assignments[target.value] = (statement, small.value)
                elif (
                    isinstance(small, cst.AnnAssign) and small.value is not None and isinstance(small.target, cst.Name)
                ):
                    self.assignments[small.target.value] = (statement, small.value)

    def _import_from(self, node: cst.ImportFrom) -> None:
        if node.relative or node.module is None or isinstance(node.names, cst.ImportStar):
            return
        module = get_full_name_for_node(node.module) or ""
        for alias in node.names:
            name = get_full_name_for_node(alias.name) or ""
            local = alias.asname.name.value if alias.asname and isinstance(alias.asname.name, cst.Name) else name
            self.imports[local] = f"{module}.{name}"

    def qualified(self, node: cst.BaseExpression) -> str | None:
        dotted = get_full_name_for_node(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        target = self.imports.get(head)
        if target is None:
            return None
        return f"{target}.{rest}" if rest else target

    def agno_class(self, node: cst.BaseExpression) -> str | None:
        qualified = self.qualified(node)
        if qualified is None or not qualified.startswith("agno."):
            return None
        return qualified.rsplit(".", 1)[-1]

    def reference(self, node: cst.BaseExpression) -> tuple[RefType, str] | None:
        """``(ref_type, attribute)`` for a registry attribute, an imported component or a function."""
        if isinstance(node, cst.Name) and node.value in self.functions:
            return "function", node.value
        qualified = self.qualified(node)
        if qualified is None:
            return None
        convention = self.convention
        registry = f"{convention.registry_module}."
        if qualified.startswith(registry):
            parts = qualified.removeprefix(registry).split(".")
            namespaces: dict[str, RefType] = {
                convention.namespace(ref_type): ref_type for ref_type in DEFAULT_NAMESPACES
            }
            if len(parts) >= 2 and parts[0] in namespaces:  # noqa: PLR2004
                return namespaces[parts[0]], parts[-1]
            return None
        for ref_type in ("agent", "team", "workflow", "function"):
            module = f"{convention.component_module(ref_type)}."
            if qualified.startswith(module):
                return ref_type, qualified.rsplit(".", 1)[-1]
        return None

    # ---------------------------------------------------------------- positions
    def span(self, node: cst.CSTNode) -> Span:
        code_range = self.ranges[node]
        start, end = code_range.start, code_range.end
        if start.line == end.line:
            return Span(start.line, start.column, end.column, end.line)
        first = self.lines[start.line - 1] if start.line - 1 < len(self.lines) else ""
        return Span(start.line, start.column, len(first), end.line)

    def note(self, node: cst.CSTNode, severity: Severity, code: str, message: str, path: str | None) -> None:
        code_range = self.ranges[node]
        self.diagnostics.append(
            CodeDiagnostic(
                severity,
                code,
                message,
                code_range.start.line,
                code_range.start.column,
                code_range.end.line,
                code_range.end.column,
                path,
            )
        )

    def own(self, path: str, error: _Unsupported, severity: Severity = "warning") -> None:
        self.note(error.node, severity, error.code, error.message, path)
        if path not in self.code_owned:
            self.code_owned.append(path)

    # ---------------------------------------------------------------- the component
    def read(self, kind: Kind | None, component_id: str | None) -> Reading:
        found = self._find(kind, component_id)
        parsed = self.reading.parsed
        parsed.diagnostics = self.diagnostics
        parsed.spans = self.spans
        parsed.code_owned = self.code_owned
        if found is None:
            return self.reading
        variable, call, component_kind = found
        parsed.kind = component_kind
        parsed.variable = variable
        self.reading.component = call
        self.reading.calls[""] = call
        raw = self._component(component_kind, call)
        parsed.config = self._normalize(component_kind, raw, call)
        return self.reading

    def candidates(self, kind: Kind | None) -> list[tuple[str, cst.Call, Kind, str | None]]:
        """Module-level names bound to an Agent/Team/Workflow call: ``(name, call, kind, literal id)``."""
        candidates: list[tuple[str, cst.Call, Kind, str | None]] = []
        for name, (_, value) in self.assignments.items():
            if not isinstance(value, cst.Call):
                continue
            component_kind = COMPONENT_CLASSES.get(self.agno_class(value.func) or "")
            if component_kind is None or (kind is not None and component_kind != kind):
                continue
            identifier = next(
                (
                    arg.value.evaluated_value
                    for arg in value.args
                    if arg.keyword is not None
                    and arg.keyword.value == "id"
                    and isinstance(arg.value, cst.SimpleString)
                    and isinstance(arg.value.evaluated_value, str)
                ),
                None,
            )
            candidates.append((name, value, component_kind, identifier))
        return candidates

    def _find(self, kind: Kind | None, component_id: str | None) -> tuple[str, cst.Call, Kind] | None:
        candidates = self.candidates(kind)
        if component_id is not None:
            matching = [item for item in candidates if item[3] == component_id]
            candidates = matching or candidates
        noun = {"agent": "an Agent", "team": "a Team", "workflow": "a Workflow"}.get(kind or "", "a component")
        if not candidates:
            self.diagnostics.append(
                CodeDiagnostic(
                    "error",
                    "component_missing",
                    f"No module-level name is bound to {noun}(…) here, so there is nothing to read.",
                    1,
                    0,
                    1,
                    0,
                )
            )
            return None
        if len(candidates) > 1:
            names = ", ".join(f"`{item[0]}`" for item in candidates)
            self.note(
                candidates[1][1],
                "warning",
                "component_ambiguous",
                f"The file defines several components ({names}); Studio reads `{candidates[0][0]}`.",
                None,
            )
        name, call, component_kind, _ = candidates[0]
        return name, call, component_kind

    def _component(self, kind: Kind, call: cst.Call) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for arg in call.args:
            if arg.keyword is None:
                self.note(arg, "warning", "positional", "Pass component settings by name.", None)
                continue
            name = arg.keyword.value
            self.reading.args[name] = arg
            self.spans[name] = self.span(arg)
            if name in CODE_ONLY:
                self.own(name, _Unsupported(arg, CODE_ONLY[name], "code_only"))
                continue
            try:
                value = self._field(kind, name, arg.value)
            except _Unsupported as error:
                self.own(name, error)
                continue
            config[name] = value
        return config

    def _field(self, kind: Kind, name: str, node: cst.BaseExpression) -> object:  # noqa: PLR0911
        if name in REF_FIELDS:
            return self._ref(REF_FIELDS[name], node)
        if name in {"input_schema", "output_schema"}:
            reference = self.reference(node)
            if reference is not None:
                return self._ref("schema", node)
            return self.literal(node)
        if name == "tools" and kind != "workflow":
            return self._tools(node)
        if name == "members" and kind == "team":
            return self._members(node)
        if name == "mode" and kind == "team":
            return self._mode(node)
        if name == "steps" and kind == "workflow":
            return self._lane("steps", node)
        return self.literal(node)

    def _ref(self, ref_type: RefType, node: cst.BaseExpression) -> object:
        if ref_type == "learning" and isinstance(node, cst.Name) and node.value in {"True", "False"}:
            return node.value == "True"
        target = self._unwrap(node)
        reference = self.reference(target)
        if reference is None or reference[0] != ref_type:
            namespace = self.convention.namespace(ref_type)
            entry = f"`{namespace}.…` from {self.convention.registry_module}"
            if isinstance(target, cst.Call):
                called = get_full_name_for_node(target.func) or "This"
                register = "as a model preset" if ref_type == "model" else "in the registry"
                raise _Unsupported(node, f"`{called}(…)` is code; register it {register} and use {entry}.", "not_ref")
            raise _Unsupported(node, f"Use a registry entry here ({entry}).", "not_ref")
        value = self.resolver.resolve(*reference)
        if value is None:
            namespace = self.convention.namespace(ref_type)
            raise _Unsupported(node, f"`{namespace}.{reference[1]}` isn't in this instance's registry.", "ref_unknown")
        return value

    def _tools(self, node: cst.BaseExpression) -> list[object]:
        node = self._unwrap(node)
        if not isinstance(node, cst.List | cst.Tuple):
            raise _Unsupported(node, "List the tools literally: `tools=[tools.a, tools.b]`.")
        tools: list[object] = []
        paths: list[list[str]] = []
        for element in node.elements:
            if isinstance(element, cst.StarredElement):
                raise _Unsupported(element, "Unpacking can't be read; list the tools one by one.")
            reference = self.reference(self._unwrap(element.value))
            if reference is None or reference[0] != "tool":
                raise _Unsupported(element, "Only registry tools (`tools.…`) can be stored in a Studio component.")
            resolved = self.resolver.resolve(*reference)
            if not isinstance(resolved, list) or not resolved:
                raise _Unsupported(element, f"`tools.{reference[1]}` isn't in this instance's registry.", "ref_unknown")
            entries = cast("list[object]", resolved)
            paths.append([f"tools[{len(tools) + offset}]" for offset in range(len(entries))])
            for offset, _ in enumerate(entries):
                self.spans[f"tools[{len(tools) + offset}]"] = self.span(element)
            tools.extend(entries)
        self.reading.elements["tools"] = list(node.elements)
        self.reading.element_paths["tools"] = paths
        return tools

    def _members(self, node: cst.BaseExpression) -> list[dict[str, str]]:
        node = self._unwrap(node)
        if not isinstance(node, cst.List | cst.Tuple):
            raise _Unsupported(node, "List the members literally: `members=[agent_a, team_b]`.")
        members: list[dict[str, str]] = []
        for index, element in enumerate(node.elements):
            reference = self.reference(self._unwrap(element.value))
            if reference is None or reference[0] not in {"agent", "team"}:
                raise _Unsupported(element, "A member is an agent or a team imported from the component modules.")
            component = self._component_id(reference[0], reference[1], element, f"members[{index}]")
            key = "agent_id" if reference[0] == "agent" else "team_id"
            members.append({"type": reference[0], key: component})
            self.spans[f"members[{index}]"] = self.span(element)
        self.reading.elements["members"] = list(node.elements)
        self.reading.element_paths["members"] = [[f"members[{index}]"] for index in range(len(members))]
        return members

    def _mode(self, node: cst.BaseExpression) -> str:
        if isinstance(node, cst.Attribute) and (self.qualified(node.value) or "").endswith("TeamMode"):
            return node.attr.value
        value = self.literal(node)
        if not isinstance(value, str):
            raise _Unsupported(node, "Set the mode as `TeamMode.coordinate` (or route, broadcast, tasks).")
        return value

    def _component_id(self, ref_type: RefType, attribute: str, node: cst.CSTNode, path: str) -> str:
        resolved = self.resolver.resolve(ref_type, attribute)
        if isinstance(resolved, str):
            return resolved
        guess = attribute.replace("_", "-")
        self.note(
            node, "warning", "component_unknown", f"`{attribute}` isn't a known {ref_type}; read as `{guess}`.", path
        )
        return guess

    # ---------------------------------------------------------------- workflows
    def _lane(self, path: str, node: cst.BaseExpression) -> list[dict[str, Any]]:
        unwrapped = self._unwrap(node)
        if not isinstance(unwrapped, cst.List | cst.Tuple):
            raise _Unsupported(node, "List the steps literally: `steps=[Step(...), ...]`.")
        return self._nodes(path, list(unwrapped.elements))

    def _nodes(self, path: str, elements: list[cst.BaseElement] | list[cst.Arg]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for index, element in enumerate(elements):
            child = f"{path}[{index}]"
            if isinstance(element, cst.StarredElement) or (isinstance(element, cst.Arg) and element.star):
                raise _Unsupported(element, "Unpacking can't be read; list the steps one by one.")
            node = self._node(child, element.value, element)
            nodes.append(node)
        self.reading.elements[path] = [element for element in elements if isinstance(element, cst.BaseElement)]
        return nodes

    def _node(self, path: str, value: cst.BaseExpression, holder: cst.CSTNode) -> dict[str, Any]:
        self.spans[path] = self.span(holder)
        target, definition = self._resolve(value)
        if definition is not None:
            self.spans[path] = self.span(definition)
        if not isinstance(target, cst.Call) or self.agno_class(target.func) not in NODE_CLASSES:
            reference = self.reference(target)
            if reference is not None:
                raise _Unsupported(
                    holder,
                    f"Wrap `{reference[1]}` in Step(name=…, {_executor_keyword(reference[0])}={reference[1]}) so the "
                    "step has a stable name.",
                    "bare_executor",
                )
            raise _Unsupported(holder, "A step is a Step, Steps, Parallel, Condition, Loop or Router call.")
        node_type = cast("str", self.agno_class(target.func))
        self.reading.calls[path] = target
        node: dict[str, Any] = {"type": node_type}
        for name, arg in self._arguments(node_type, target, path):
            self.reading.args[f"{path}.{name}"] = arg
            self.spans[f"{path}.{name}"] = self.span(arg)
            self._node_field(node_type, node, name, arg, path)
        if node_type == "Parallel":
            positional = [arg for arg in target.args if arg.keyword is None]
            node["steps"] = self._nodes(f"{path}.steps", positional)
        return node

    def _arguments(self, node_type: str, call: cst.Call, path: str) -> list[tuple[str, cst.Arg]]:
        order = POSITIONAL.get(node_type, ())
        found: list[tuple[str, cst.Arg]] = []
        for index, arg in enumerate(call.args):
            if arg.keyword is not None:
                found.append((arg.keyword.value, arg))
            elif node_type == "Parallel":
                continue
            elif index < len(order):
                found.append((order[index], arg))
            else:
                self.own(path, _Unsupported(arg, f"{node_type} doesn't take this many positional arguments."))
        return found

    def _node_field(self, node_type: str, node: dict[str, Any], name: str, arg: cst.Arg, path: str) -> None:
        field_path = f"{path}.{name}"
        try:
            if node_type == "Step" and name in STEP_EXECUTORS:
                key, ref_type = STEP_EXECUTORS[name]
                node[key] = self._executor(ref_type, arg.value, field_path)
            elif name in LANES.get(node_type, ()):
                node[name] = self._lane(field_path, arg.value)
            elif name in CALLABLES.get(node_type, {}):
                value, kind = self._callable(node_type, arg.value)
                node[name] = value
                node[CALLABLES[node_type][name]] = kind
            elif name == "human_review":
                node[name] = self._review(arg.value)
            else:
                node[name] = self.literal(arg.value)
        except _Unsupported as error:
            self.own(field_path, error)

    def _executor(self, ref_type: RefType, node: cst.BaseExpression, path: str) -> str:
        target, _ = self._resolve(node)
        reference = self.reference(target)
        if reference is None or reference[0] != ref_type:
            module = self.convention.component_module(ref_type)
            raise _Unsupported(node, f"Name a {ref_type} imported from {module}.", "not_ref")
        if ref_type == "function":
            resolved = self.resolver.resolve("function", reference[1])
            return resolved if isinstance(resolved, str) else reference[1]
        return self._component_id(ref_type, reference[1], node, path)

    def _callable(self, node_type: str, node: cst.BaseExpression) -> tuple[object, str]:
        target, _ = self._resolve(node)
        if isinstance(target, cst.Lambda):
            raise _Unsupported(node, "A lambda can't be stored; register a function and name it, or use CEL.")
        reference = self.reference(target)
        if reference is not None and reference[0] == "function":
            resolved = self.resolver.resolve("function", reference[1])
            return (resolved if isinstance(resolved, str) else reference[1]), "function"
        value = self.literal(node)
        if isinstance(value, bool) and node_type == "Condition":
            return value, "bool"
        if isinstance(value, str):
            return value, "cel"
        raise _Unsupported(node, "Use a CEL expression (a string) or a registered function.")

    def _review(self, node: cst.BaseExpression) -> dict[str, Any]:
        target, _ = self._resolve(node)
        if not isinstance(target, cst.Call) or self.agno_class(target.func) != "HumanReview":
            raise _Unsupported(node, "Set the review with HumanReview(…).")
        review: dict[str, Any] = {}
        for arg in target.args:
            if arg.keyword is None:
                raise _Unsupported(arg, "Pass HumanReview settings by name.")
            review[arg.keyword.value] = self.literal(arg.value)
        return review

    # ---------------------------------------------------------------- literals
    def _unwrap(self, node: cst.BaseExpression) -> cst.BaseExpression:
        target, _ = self._resolve(node)
        return target

    def _resolve(self, node: cst.BaseExpression) -> tuple[cst.BaseExpression, cst.CSTNode | None]:
        """A module-level name becomes its value (and the statement defining it); anything else stays."""
        definition: cst.CSTNode | None = None
        depth = 0
        while isinstance(node, cst.Name) and node.value in self.assignments and node.value not in self.imports:
            if depth > MAX_RESOLVE_DEPTH or node.value in self.resolving:
                raise _Unsupported(node, f"`{node.value}` refers to itself.")
            statement, value = self.assignments[node.value]
            definition = definition or statement
            node = value
            depth += 1
        return node, definition

    def literal(self, node: cst.BaseExpression) -> Any:  # noqa: ANN401, C901, PLR0911, PLR0912
        target, definition = self._resolve(node)
        if definition is not None and isinstance(node, cst.Name):
            self.resolving.append(node.value)
            try:
                return self.literal(target)
            finally:
                self.resolving.pop()
        node = target
        if isinstance(node, cst.SimpleString):
            return node.evaluated_value
        if isinstance(node, cst.ConcatenatedString):
            value = node.evaluated_value
            if value is None:
                raise _Unsupported(node, "An f-string can't be stored; write the text out.", "f_string")
            return value
        if isinstance(node, cst.FormattedString):
            raise _Unsupported(node, "An f-string can't be stored; write the text out.", "f_string")
        if isinstance(node, cst.Integer | cst.Float):
            return node.evaluated_value
        if isinstance(node, cst.UnaryOperation) and isinstance(node.operator, cst.Minus):
            inner = self.literal(node.expression)
            if isinstance(inner, int | float) and not isinstance(inner, bool):
                return -inner
        if isinstance(node, cst.Name) and node.value in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.value]
        if isinstance(node, cst.List | cst.Tuple):
            items: list[Any] = []
            for element in node.elements:
                if isinstance(element, cst.StarredElement):
                    raise _Unsupported(element, "Unpacking can't be stored; list the items.")
                items.append(self.literal(element.value))
            return items
        if isinstance(node, cst.Dict):
            entries: dict[str, Any] = {}
            for element in node.elements:
                if not isinstance(element, cst.DictElement):
                    raise _Unsupported(element, "Unpacking can't be stored; list the entries.")
                key = self.literal(element.key)
                if not isinstance(key, str):
                    raise _Unsupported(element.key, "Keys must be strings to be stored as JSON.")
                entries[key] = self.literal(element.value)
            return entries
        if isinstance(node, cst.BinaryOperation) and isinstance(node.operator, cst.Add):
            left, right = self.literal(node.left), self.literal(node.right)
            if isinstance(left, str) and isinstance(right, str):
                return left + right
        if isinstance(node, cst.Lambda):
            raise _Unsupported(node, "A lambda can't be stored in a Studio component.", "callable")
        if isinstance(node, cst.Call):
            name = get_full_name_for_node(node.func) or "a call"
            raise _Unsupported(node, f"`{name}(…)` is code: Studio can only store literals and registry entries.")
        name = get_full_name_for_node(node)
        if name is not None:
            raise _Unsupported(node, f"`{name}` is defined elsewhere; Studio can only store literals here.", "name")
        raise _Unsupported(node, "This expression can't be stored in a Studio component.")

    # ---------------------------------------------------------------- normalization
    def _normalize(self, kind: Kind, raw: dict[str, Any], call: cst.Call) -> dict[str, Any] | None:
        problems = shape_errors(kind, raw)
        if problems:
            for problem in problems:
                anchor = self.reading.args.get(problem.path.split(".", 1)[0].split("[", 1)[0], call)
                self.note(anchor, "error", problem.code, problem.message, problem.path)
            return None
        return parse(kind, raw).dump()


def _executor_keyword(ref_type: RefType) -> str:
    return {"agent": "agent", "team": "team", "workflow": "workflow"}.get(ref_type, "executor")


def owned_paths(parsed: Parsed) -> Callable[[str], bool]:
    """Whether a config path is code-owned, itself or through a parent."""
    owned = tuple(parsed.code_owned)

    def check(path: str) -> bool:
        return any(path == prefix or path.startswith((f"{prefix}.", f"{prefix}[")) for prefix in owned)

    return check


__all__ = [
    "CODE_ONLY",
    "CodeDiagnostic",
    "Lookup",
    "Parsed",
    "Reading",
    "Resolver",
    "owned_paths",
    "parse_source",
    "read_source",
]
