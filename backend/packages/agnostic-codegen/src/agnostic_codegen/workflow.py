"""Workflow config → Python: one ``Workflow(...)`` with its step tree, written the way a person would.

Only what differs from agno's defaults is written (a config always carries every key, code doesn't need to).
Executors are imported by name from the component and function modules. Containers that are a Router's choices
are defined first as module-level variables (``investigate = Parallel(...)``), and a Router selector too long for
its line becomes a constant split at its ternaries, so the router itself stays readable.
"""

from __future__ import annotations

import itertools
import keyword
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agnostic_cel import CelSyntaxError, parse, ternary_chain
from agnostic_codegen.convention import RegistryConvention, snake
from agnostic_codegen.generate import INDENT, Code, Generated, Imports, render_literal
from agnostic_spec.v3_1 import NODE_MODELS, WorkflowConfig, layout
from agnostic_spec.v3_1.refs import schema_name
from agnostic_spec.v3_1.workflow import default_review

LINE_LENGTH = 120
WORKFLOW_MODULE = "agno.workflow"
REVIEW_MODULE = "agno.workflow.types"
EXECUTOR_KWARGS: Mapping[str, tuple[str, str]] = {
    "agent_id": ("agent", "agent"),
    "team_id": ("team", "team"),
    "workflow_id": ("workflow", "workflow"),
    "executor_ref": ("executor", "function"),
}
# Keyword order per node type, as the design reads; anything else follows in the order agno writes it.
NODE_ORDER: Mapping[str, tuple[str, ...]] = {
    "Step": ("name", "agent_id", "team_id", "workflow_id", "executor_ref", "step_id", "description"),
    "Steps": ("name", "steps", "description"),
    "Parallel": ("name", "description"),
    "Condition": ("name", "evaluator", "steps", "else_steps", "description"),
    "Loop": ("name", "steps", "end_condition", "max_iterations", "forward_iteration_output", "description"),
    "Router": ("name", "selector", "choices", "description"),
}
DERIVED = frozenset({"type", "evaluator_type", "end_condition_type", "selector_type"})


@dataclass(slots=True)
class NodeWriter:
    """Writes workflow nodes as code. Edits of an existing file turn hoisting off and name imports its own way."""

    convention: RegistryConvention
    imports: Imports
    hoisted: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    taken: set[str] = field(default_factory=set[str])
    hoisting: bool = True
    refer: Callable[[str, str], str] | None = None
    """``(module, name) â†’ expression`` naming an imported object; by default it imports the name."""

    def name(self, module: str, attribute: str) -> str:
        if self.refer is not None:
            return self.refer(module, attribute)
        self.imports.add(module, attribute)
        return attribute

    def reserve(self, wanted: str, *, constant: bool = False) -> str:
        base = snake(wanted.replace("&", " and ")) or "step"
        if constant:
            base = base.upper()
        name = base
        counter = 2
        while name in self.taken or keyword.iskeyword(name):
            name = f"{base}_{counter}"
            counter += 1
        self.taken.add(name)
        return name

    def executor(self, field_name: str, value: str) -> Code:
        _, ref_type = EXECUTOR_KWARGS[field_name]
        attribute = self.convention.attribute(ref_type, value)  # pyright: ignore[reportArgumentType]
        self.taken.add(attribute)
        return Code(self.name(self.convention.component_module(ref_type), attribute))  # pyright: ignore[reportArgumentType]

    def function(self, value: str) -> Code:
        attribute = self.convention.attribute("function", value)
        self.taken.add(attribute)
        return Code(self.name(self.convention.functions_module, attribute))

    # ---------------------------------------------------------------- nodes
    def node(self, data: Mapping[str, Any], depth: int, *, hoist: bool = False) -> Code:
        node_type = str(data.get("type") or "Step")
        cls = self.name(WORKFLOW_MODULE, node_type)
        positional: list[str] = []
        keywords: list[tuple[str, str]] = []
        for name in node_order(node_type, data):
            value = data[name]
            if name in DERIVED or omitted(node_type, name, value):
                continue
            if node_type == "Parallel" and name == "steps":
                positional.extend(self.node(child, depth + 1).text for child in value)
                continue
            keywords.append(self.keyword(node_type, name, value, data, depth))
        call = _call(cls, positional, keywords, depth, explode=node_type != "Step")
        if not hoist or not self.hoisting:
            return Code(call)
        variable = self.reserve(str(data.get("name") or node_type))
        self.hoisted.append((variable, call.replace("\n" + INDENT * depth, "\n")))
        return Code(variable)

    def keyword(self, node_type: str, name: str, value: Any, data: Mapping[str, Any], depth: int) -> tuple[str, str]:  # noqa: ANN401
        """``(keyword, code)`` for one config field of a node at ``depth``."""
        if name in EXECUTOR_KWARGS and isinstance(value, str):
            return EXECUTOR_KWARGS[name][0], self.executor(name, value).text
        if name in {"steps", "else_steps", "choices"} and isinstance(value, list):
            hoist = node_type == "Router"
            items: list[Any] = value  # pyright: ignore[reportUnknownVariableType]
            children = [
                self.node(child, depth + 2, hoist=hoist and str(child.get("type") or "Step") != "Step").text
                for child in items
            ]
            return name, _list(children, depth + 1)
        if name in {"evaluator", "end_condition", "selector"}:
            return name, self._callable(name, value, data, depth)
        if name == "human_review" and isinstance(value, Mapping):
            return name, self._review(value, depth + 1)  # pyright: ignore[reportUnknownArgumentType]
        return name, render_literal(value, depth + 1)

    def _callable(self, name: str, value: object, data: Mapping[str, Any], depth: int) -> str:
        kind = data.get(f"{name}_type")
        if kind == "function" and isinstance(value, str):
            return self.function(value).text
        if kind == "cel" and isinstance(value, str) and name == "selector" and self.hoisting:
            width = len(INDENT) * (depth + 1) + len(name) + len(repr(value)) + 2
            if width > LINE_LENGTH:
                return self._constant(str(data.get("name") or name), value)
        return render_literal(value, depth + 1)

    def _constant(self, wanted: str, expression: str) -> str:
        """A long selector as ``NAME = ("a ? x" " : b ? y" " : z")``: one line per branch of the ternary chain."""
        parts = segments(expression)
        variable = self.reserve(wanted, constant=True)
        if len(parts) == 1:
            self.hoisted.insert(0, (variable, render_literal(expression, 0)))
        else:
            body = "".join(f"{INDENT}{render_literal(segment, 1)}\n" for segment in parts)
            self.hoisted.insert(0, (variable, f"(\n{body})"))
        return variable

    def _review(self, review: Mapping[str, Any], depth: int) -> str:
        """Only what differs from ``HumanReview()``'s own defaults: those apply once a review is given."""
        cls = self.name(REVIEW_MODULE, "HumanReview")
        defaults = default_review("Step")
        keywords = [
            (name, render_literal(value, depth + 1))
            for name, value in review.items()
            if name not in defaults or defaults[name] != value
        ]
        return _call(cls, [], keywords, depth, explode=True)


def generate_workflow(config: WorkflowConfig, convention: RegistryConvention | None = None) -> Generated:
    convention = convention or RegistryConvention()
    imports = Imports()
    imports.add(WORKFLOW_MODULE, "Workflow")
    data = config.dump()
    variable = snake(str(data.get("id") or data.get("name") or "workflow"))
    emitter = NodeWriter(convention, imports, taken={variable, *_executor_names(data.get("steps") or [], convention)})
    generated = Generated(code="", variable=variable)

    keywords: list[tuple[str, str]] = []
    for name in _workflow_order(data):
        value = data[name]
        if WorkflowConfig.defaults.get(name, object()) == value:
            continue
        if name == "steps":
            children = [emitter.node(step, 2).text for step in value]
            keywords.append((name, _list(children, 1)))
        elif name == "input_schema" and schema_name(value) is not None:
            namespace = convention.namespace("schema")
            imports.add(convention.registry_module, namespace)
            keywords.append((name, f"{namespace}.{convention.attribute('schema', str(value))}"))
        else:
            keywords.append((name, render_literal(value, 1)))

    blocks = [imports.render()]
    blocks.extend(f"{name} = {code}" for name, code in emitter.hoisted)
    blocks.append(f"{variable} = {_call('Workflow', [], keywords, 0, explode=True)}")
    generated.code = "\n\n".join(blocks) + "\n"
    return generated


def _executor_names(steps: list[Any], convention: RegistryConvention) -> set[str]:
    """Names the imports will bind, so a hoisted variable never shadows one."""
    names: set[str] = set()
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        node: Mapping[str, Any] = step  # pyright: ignore[reportUnknownVariableType]
        for field_name, (_, ref_type) in EXECUTOR_KWARGS.items():
            value = node.get(field_name)
            if isinstance(value, str):
                names.add(convention.attribute(ref_type, value))  # pyright: ignore[reportArgumentType]
        for lane in ("steps", "else_steps", "choices"):
            names |= _executor_names(list(node.get(lane) or []), convention)
        for name in ("evaluator", "end_condition", "selector"):
            if node.get(f"{name}_type") == "function" and isinstance(node.get(name), str):
                names.add(convention.attribute("function", str(node[name])))
    return names


def _workflow_order(data: Mapping[str, Any]) -> list[str]:
    known = ["id", "name", "description", "steps"]
    for section in layout("workflow"):
        known.extend(name for name in section["fields"] if name not in known)
    ordered = [name for name in known if name in data]
    ordered.extend(sorted(name for name in data if name not in ordered))
    return ordered


def node_order(node_type: str, data: Mapping[str, Any]) -> list[str]:
    preferred = list(NODE_ORDER.get(node_type, ("name",)))
    model = NODE_MODELS.get(node_type)
    agno_order = list(model.always + model.when_set) if model is not None else []
    if node_type == "Parallel":
        preferred = ["steps", *preferred]
    ordered = [name for name in preferred if name in data]
    ordered.extend(name for name in agno_order if name in data and name not in ordered)
    ordered.extend(sorted(name for name in data if name not in ordered))
    return ordered


# Written even at agno's default, because a reader expects to see them.
ALWAYS_WRITTEN: Mapping[str, frozenset[str]] = {"Loop": frozenset({"max_iterations"})}


def omitted(node_type: str, name: str, value: object) -> bool:
    if value is None:
        return True
    if name in ALWAYS_WRITTEN.get(node_type, frozenset()):
        return False
    if name == "human_review":
        return value == default_review(node_type)
    if name == "else_steps" and value == []:
        return True
    if node_type == "Condition" and name == "evaluator" and value is True:
        return True
    model = NODE_MODELS.get(node_type)
    return model is not None and name in model.defaults and model.defaults[name] == value


def _call(cls: str, positional: list[str], keywords: list[tuple[str, str]], depth: int, *, explode: bool) -> str:
    arguments = [*positional, *(f"{name}={value}" for name, value in keywords)]
    if not arguments:
        return f"{cls}()"
    if not explode:
        return f"{cls}({', '.join(arguments)})"
    pad = INDENT * (depth + 1)
    body = "".join(f"{pad}{argument},\n" for argument in arguments)
    return f"{cls}(\n{body}{INDENT * depth})"


def _list(items: list[str], depth: int) -> str:
    if not items:
        return "[]"
    pad = INDENT * (depth + 1)
    return "[\n" + "".join(f"{pad}{item},\n" for item in items) + f"{INDENT * depth}]"


def segments(expression: str) -> list[str]:
    try:
        chain = ternary_chain(parse(expression))
    except CelSyntaxError:
        return [expression]
    if len(chain) == 1:
        return [expression]
    cuts = [0]
    for conditional in chain[:-1]:
        then = getattr(conditional, "then", None)
        if then is None:
            return [expression]
        cuts.append(then.span.end)
    cuts.append(len(expression))
    return [expression[start:end] for start, end in itertools.pairwise(cuts) if expression[start:end]]


__all__ = ["DERIVED", "EXECUTOR_KWARGS", "NodeWriter", "generate_workflow", "node_order", "omitted", "segments"]
