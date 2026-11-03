"""Every registry reference a config makes, with the field path that makes it."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from agnostic_spec.v3_1.base import ComponentConfig, SharedConfig
from agnostic_spec.v3_1.refs import ModelRef, ToolRef, learning_name, schema_name
from agnostic_spec.v3_1.team import TeamConfig
from agnostic_spec.v3_1.workflow import ConditionNode, LoopNode, RouterNode, StepNode, WorkflowConfig, iter_nodes

RefType = Literal[
    "model", "tool", "knowledge", "schema", "memory_manager", "learning", "agent", "team", "workflow", "function"
]
STEP_EXECUTORS: tuple[tuple[str, RefType], ...] = (
    ("agent_id", "agent"),
    ("team_id", "team"),
    ("workflow_id", "workflow"),
    ("executor_ref", "function"),
)
MODEL_FIELDS = ("model", "reasoning_model", "parser_model", "output_model", "followup_model")


@dataclass(frozen=True, slots=True)
class RefUse:
    path: str
    type: RefType
    name: str
    """The registry entry's name (for memory managers: its registry id; for members and steps: the component id)."""
    function: str | None = None
    """For a toolkit function: which function of the toolkit."""


def iter_refs(config: ComponentConfig) -> Iterator[RefUse]:
    if isinstance(config, SharedConfig):
        yield from _models(config)
        yield from _tools(config)
        yield from _context(config)
    if isinstance(config, TeamConfig):
        for index, member in enumerate(config.members or []):
            if member.component_id:
                yield RefUse(f"members[{index}]", member.type, member.component_id)
    if isinstance(config, WorkflowConfig):
        yield from _workflow(config)


def _models(config: SharedConfig) -> Iterator[RefUse]:
    extra = config.model_extra or {}
    for field in MODEL_FIELDS:
        raw: object = getattr(config, field, None) if field in type(config).model_fields else extra.get(field)
        model = ModelRef.parse(raw) if raw is not None else None
        if model is not None:
            yield RefUse(field, "model", model.id)


def _tools(config: SharedConfig) -> Iterator[RefUse]:
    for index, tool in enumerate(config.tools or []):
        if isinstance(tool, ToolRef):
            yield RefUse(f"tools[{index}]", "tool", tool.registry_name, function=tool.name if tool.toolkit else None)


def _context(config: SharedConfig) -> Iterator[RefUse]:
    if config.knowledge is not None:
        yield RefUse("knowledge", "knowledge", config.knowledge.name)
    for field, value in (("input_schema", config.input_schema), ("output_schema", config.output_schema)):
        name = schema_name(value)
        if name is not None:
            yield RefUse(field, "schema", name)
    if config.memory_manager is not None:
        yield RefUse("memory_manager", "memory_manager", config.memory_manager.registry_id)
    learning = learning_name(config.learning)
    if learning is not None:
        yield RefUse("learning", "learning", learning)


def _workflow(config: WorkflowConfig) -> Iterator[RefUse]:
    name = schema_name(config.input_schema)
    if name is not None:
        yield RefUse("input_schema", "schema", name)
    for info in iter_nodes(config):
        node = info.node
        if isinstance(node, StepNode):
            for field, ref_type in STEP_EXECUTORS:
                value = getattr(node, field)
                if isinstance(value, str) and value:
                    yield RefUse(info.path, ref_type, value)
            continue
        for field, kind_field in (("evaluator", "evaluator_type"), ("end_condition", "end_condition_type")):
            if isinstance(node, ConditionNode | LoopNode) and field in type(node).model_fields:
                function = node.value(field)
                if node.value(kind_field) == "function" and isinstance(function, str):
                    yield RefUse(f"{info.path}.{field}", "function", function)
        if isinstance(node, RouterNode) and node.value("selector_type") == "function" and node.selector:
            yield RefUse(f"{info.path}.selector", "function", node.selector)
