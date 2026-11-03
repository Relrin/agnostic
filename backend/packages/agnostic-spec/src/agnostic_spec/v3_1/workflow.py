"""``Workflow.to_dict()`` as typed fields: the workflow settings and its tree of steps.

agno writes workflows in full: every step carries all of its keys (``None`` included) and a complete
``human_review``, whatever was set. :meth:`WorkflowConfig.dump` writes the same shape, so a config built by Studio
with only the values someone chose is stored exactly as agno would store it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Discriminator, Tag

from agnostic_spec.fields import meta_field
from agnostic_spec.v3_1.base import ComponentConfig, Kind

NodeType = Literal["Step", "Steps", "Parallel", "Condition", "Loop", "Router"]
NODE_TYPES: tuple[NodeType, ...] = ("Step", "Steps", "Parallel", "Condition", "Loop", "Router")
CONTAINER_TYPES: frozenset[str] = frozenset({"Steps", "Parallel", "Condition", "Loop", "Router"})
Lane = Literal["steps", "else_steps", "choices"]
MAX_DEPTH = 10

OnReject = Literal["skip", "cancel", "else", "retry"]
OnError = Literal["skip", "fail", "pause"]
OnTimeout = Literal["cancel", "skip", "approve"]
CallableType = Literal["cel", "function"]

# agno's own test for a CEL expression: anything but a plain identifier that has one of these in it.
_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_CEL_MARKS = (
    *(".", "(", ")", "[", "]", "==", "!=", "<=", ">=", "<", ">", "&&", "||", "!", "+", "-", "*", "/", "%"),
    *("?", ":", '"', "'", "true", "false", " in "),
)


def looks_like_cel(value: str) -> bool:
    """A plain identifier names a registered function; anything else with an operator in it is a CEL expression."""
    if _IDENTIFIER.match(value):
        return False
    return any(mark in value for mark in _CEL_MARKS)


class HumanReview(BaseModel):
    """``HumanReview.to_dict()``. Which fields a node may use depends on its type (:data:`HUMAN_REVIEW_SUPPORT`)."""

    model_config = ConfigDict(extra="allow")

    requires_confirmation: bool | None = meta_field("confirmation", "Ask before it runs", widget="switch", order=1)
    confirmation_message: str | None = meta_field("confirmation", "Question", order=2)
    requires_user_input: bool | None = meta_field("user_input", "Ask for input", widget="switch", order=1)
    user_input_message: str | None = meta_field("user_input", "Prompt", order=2)
    user_input_schema: list[dict[str, Any]] | None = meta_field("user_input", "Fields", widget="json", order=3)
    allow_multiple_selections: bool | None = meta_field("user_input", "Allow several routes", widget="switch", order=4)
    requires_output_review: bool | None = meta_field("output_review", "Review the output", widget="switch", order=1)
    output_review_message: str | None = meta_field("output_review", "Question", order=2)
    requires_iteration_review: bool | None = meta_field(
        "iteration_review", "Review each iteration", widget="switch", order=1
    )
    iteration_review_message: str | None = meta_field("iteration_review", "Question", order=2)
    on_reject: OnReject | None = meta_field("behaviour", "When rejected", widget="select", order=1)
    on_error: OnError | None = meta_field("behaviour", "When a step fails", widget="select", order=2)
    max_retries: int | None = meta_field("behaviour", "Retries after a rejection", widget="number", order=3)
    timeout: int | None = meta_field("behaviour", "Expires after (seconds)", widget="number", order=4)
    on_timeout: OnTimeout | None = meta_field("behaviour", "When it expires", widget="select", order=5)

    def canonical(self, node_type: str = "Step") -> dict[str, Any]:
        """Every field, as agno writes it.

        An empty review is the node type's default one; once anything is set, agno fills the rest with
        ``HumanReview()``'s own defaults (so a Condition's rejection no longer goes to its else branch).
        """
        given = self.model_dump(mode="json", exclude_unset=True)
        given.update(self.model_extra or {})
        data = default_review(node_type if not given else "Step")
        data.update(given)
        return data


# Field defaults live in one place, because ``meta_field`` makes every field absent by default.
_REVIEW_DEFAULTS: Mapping[str, Any] = {
    "requires_confirmation": False,
    "confirmation_message": None,
    "requires_user_input": False,
    "user_input_message": None,
    "user_input_schema": None,
    "allow_multiple_selections": False,
    "requires_output_review": False,
    "output_review_message": None,
    "requires_iteration_review": False,
    "iteration_review_message": None,
    "on_reject": "skip",
    "on_error": "skip",
    "max_retries": 3,
    "timeout": None,
    "on_timeout": "cancel",
}


def default_review(node_type: str) -> dict[str, Any]:
    """The ``human_review`` agno writes for a node nobody configured (a Condition rejects into its else branch)."""
    review = dict(_REVIEW_DEFAULTS)
    if node_type == "Condition":
        review["on_reject"] = "else"
    return review


# Which ``human_review`` fields each node type acts on. Flags (``requires_*``) outside the set make agno refuse the
# node; other fields outside it are ignored by agno.
REVIEW_GROUPS: Mapping[str, tuple[str, ...]] = {
    "confirmation": ("requires_confirmation", "confirmation_message"),
    "user_input": ("requires_user_input", "user_input_message", "user_input_schema"),
    "route_selection": ("allow_multiple_selections",),
    "output_review": ("requires_output_review", "output_review_message"),
    "iteration_review": ("requires_iteration_review", "iteration_review_message"),
    "rejection": ("on_reject", "max_retries"),
    "errors": ("on_error",),
    "timeout": ("timeout", "on_timeout"),
}
HUMAN_REVIEW_SUPPORT: Mapping[str, tuple[str, ...]] = {
    "Step": ("confirmation", "user_input", "output_review", "rejection", "errors", "timeout"),
    "Router": ("confirmation", "user_input", "route_selection", "output_review", "rejection"),
    "Loop": ("confirmation", "iteration_review", "rejection"),
    "Condition": ("confirmation", "rejection", "errors"),
    "Steps": ("confirmation", "rejection"),
    "Parallel": (),
}
REVIEW_FLAGS: tuple[str, ...] = (
    "requires_confirmation",
    "requires_user_input",
    "requires_output_review",
    "requires_iteration_review",
)


def review_fields(node_type: str) -> frozenset[str]:
    """``human_review`` fields a node of ``node_type`` may set."""
    return frozenset(field for group in HUMAN_REVIEW_SUPPORT.get(node_type, ()) for field in REVIEW_GROUPS[group])


class Node(BaseModel):
    """One element of a step list. Subclasses name the keys agno always writes and the ones it writes when set."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    always: ClassVar[tuple[str, ...]] = ()
    when_set: ClassVar[tuple[str, ...]] = ()
    defaults: ClassVar[Mapping[str, Any]] = {}
    lanes: ClassVar[tuple[Lane, ...]] = ()

    name: str | None = meta_field("settings", "Name", order=1)
    description: str | None = meta_field("settings", "Description", widget="textarea", order=2)

    @property
    def node_type(self) -> str:
        return str(getattr(self, "type", "Step"))

    def value(self, name: str) -> Any:  # noqa: ANN401
        """The field as agno would see it: set, or agno's default."""
        current = getattr(self, name, None)
        if current is None and name in self.defaults:
            return self.defaults[name]
        return current

    def children(self, lane: Lane) -> list[StepTree]:
        found: list[StepTree] | None = getattr(self, lane, None)
        return list(found or [])

    def review(self) -> dict[str, Any]:
        """The node's ``human_review`` with agno's defaults filled in."""
        raw: HumanReview | None = getattr(self, "human_review", None)
        return default_review(self.node_type) if raw is None else raw.canonical(self.node_type)

    def canonical(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.node_type}
        for name in self.always:
            if name == "human_review":
                data[name] = self.review()
            elif name in self.lanes:
                data[name] = [child.canonical() for child in self.children(name)]  # pyright: ignore[reportArgumentType]
            else:
                data[name] = _json(self.value(name))
        for name in self.when_set:
            current = getattr(self, name, None)
            if current is not None:
                data[name] = _json(current)
        for key, extra in (self.model_extra or {}).items():
            data.setdefault(key, extra)
        return data


class StepNode(Node):
    """Runs one executor: an agent, a team, a nested workflow or a registered function."""

    always = (
        "name",
        "step_id",
        "description",
        "max_retries",
        "skip_on_failure",
        "strict_input_validation",
        "add_workflow_history",
        "num_history_runs",
        "human_review",
    )
    when_set = ("agent_id", "team_id", "workflow_id", "executor_ref")
    defaults = {"max_retries": 3, "skip_on_failure": False, "strict_input_validation": False, "num_history_runs": 3}

    type: Literal["Step"] = "Step"
    step_id: str | None = meta_field(
        "settings", "Step id", help="Stable key for the executor's pin; the name is used when it's empty.", order=3
    )
    agent_id: str | None = meta_field("executor", "Agent", widget="executor", order=1)
    team_id: str | None = meta_field("executor", "Team", widget="executor", order=2)
    workflow_id: str | None = meta_field("executor", "Workflow", widget="executor", order=3)
    executor_ref: str | None = meta_field("executor", "Function", widget="executor", order=4)
    max_retries: int | None = meta_field("settings", "Retries", widget="number", default=3, order=10)
    skip_on_failure: bool | None = meta_field(
        "settings", "Skip when it fails", widget="switch", default=False, order=11
    )
    strict_input_validation: bool | None = meta_field(
        "settings", "Validate the input strictly", widget="switch", default=False, order=12
    )
    add_workflow_history: bool | None = meta_field("history", "Add workflow history", widget="switch", order=1)
    num_history_runs: int | None = meta_field("history", "Runs of history", widget="number", default=3, order=2)
    human_review: HumanReview | None = meta_field("review", "Human review", widget="human_review", order=1)

    def executors(self) -> list[tuple[str, str]]:
        """``(field, value)`` for every executor the step names."""
        return [
            (field, value)
            for field in ("agent_id", "team_id", "workflow_id", "executor_ref")
            if isinstance(value := getattr(self, field), str) and value
        ]


class StepsNode(Node):
    """Runs its steps in sequence, as one named group."""

    always = ("name", "description", "steps", "human_review")
    lanes = ("steps",)

    type: Literal["Steps"] = "Steps"
    steps: list[StepTree] | None = meta_field("steps", "Steps", widget="steps", order=1)
    human_review: HumanReview | None = meta_field("review", "Human review", widget="human_review", order=1)


class ParallelNode(Node):
    """Runs its branches at once. Nothing inside it can pause for a person."""

    always = ("name", "description", "steps")
    lanes = ("steps",)

    type: Literal["Parallel"] = "Parallel"
    steps: list[StepTree] | None = meta_field("steps", "Branches", widget="steps", order=1)


class ConditionNode(Node):
    """Runs ``steps`` when the evaluator holds, ``else_steps`` otherwise."""

    always = ("name", "description", "steps", "else_steps", "evaluator", "evaluator_type", "human_review")
    lanes = ("steps", "else_steps")

    type: Literal["Condition"] = "Condition"
    evaluator: bool | str | None = meta_field(
        "settings",
        "Evaluator",
        help="A CEL expression returning bool, or a registered function.",
        widget="cel",
        order=3,
    )
    evaluator_type: Literal["cel", "function", "bool"] | None = None
    steps: list[StepTree] | None = meta_field("steps", "When true", widget="steps", order=1)
    else_steps: list[StepTree] | None = meta_field("steps", "Else", widget="steps", order=2)
    human_review: HumanReview | None = meta_field("review", "Human review", widget="human_review", order=1)

    def value(self, name: str) -> Any:  # noqa: ANN401
        if name == "evaluator":
            return True if self.evaluator is None else self.evaluator
        if name == "evaluator_type":
            return self.evaluator_type or _callable_type(self.value("evaluator"))
        return super().value(name)


class LoopNode(Node):
    """Repeats its steps until the end condition holds or ``max_iterations`` is reached."""

    always = (
        "name",
        "description",
        "steps",
        "max_iterations",
        "end_condition",
        "end_condition_type",
        "forward_iteration_output",
        "human_review",
    )
    defaults = {"max_iterations": 3, "forward_iteration_output": False}
    lanes = ("steps",)

    type: Literal["Loop"] = "Loop"
    steps: list[StepTree] | None = meta_field("steps", "Steps", widget="steps", order=1)
    max_iterations: int | None = meta_field("settings", "Max iterations", widget="number", default=3, order=3)
    end_condition: str | None = meta_field(
        "settings",
        "End condition",
        help="A CEL expression returning bool, or a registered function. Empty runs every iteration.",
        widget="cel",
        order=4,
    )
    end_condition_type: CallableType | None = None
    forward_iteration_output: bool | None = meta_field(
        "settings", "Pass each iteration's output to the next", widget="switch", default=False, order=5
    )
    human_review: HumanReview | None = meta_field("review", "Human review", widget="human_review", order=1)

    def value(self, name: str) -> Any:  # noqa: ANN401
        if name == "end_condition_type":
            return self.end_condition_type or _callable_type(self.end_condition)
        return super().value(name)


class RouterNode(Node):
    """Runs the choice its selector names (or the one a person picks)."""

    always = ("name", "description", "choices", "selector", "selector_type", "human_review")
    lanes = ("choices",)

    type: Literal["Router"] = "Router"
    selector: str | None = meta_field(
        "settings",
        "Selector",
        help="A CEL expression returning a choice's name, or a registered function.",
        widget="cel",
        order=3,
    )
    selector_type: CallableType | None = None
    choices: list[StepTree] | None = meta_field("steps", "Choices", widget="steps", order=1)
    human_review: HumanReview | None = meta_field("review", "Human review", widget="human_review", order=1)

    def value(self, name: str) -> Any:  # noqa: ANN401
        if name == "selector_type":
            return self.selector_type or _callable_type(self.selector)
        return super().value(name)


def _node_type(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("type") or "Step")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return str(getattr(value, "type", "Step"))


StepTree = Annotated[
    Annotated[StepNode, Tag("Step")]
    | Annotated[StepsNode, Tag("Steps")]
    | Annotated[ParallelNode, Tag("Parallel")]
    | Annotated[ConditionNode, Tag("Condition")]
    | Annotated[LoopNode, Tag("Loop")]
    | Annotated[RouterNode, Tag("Router")],
    Discriminator(_node_type),
]
NODE_MODELS: Mapping[str, type[Node]] = {
    "Step": StepNode,
    "Steps": StepsNode,
    "Parallel": ParallelNode,
    "Condition": ConditionNode,
    "Loop": LoopNode,
    "Router": RouterNode,
}
for _model in NODE_MODELS.values():
    _model.model_rebuild()


class WorkflowConfig(ComponentConfig):
    kind: ClassVar[Kind] = "workflow"

    always: ClassVar[tuple[str, ...]] = (
        "overwrite_db_session_state",
        "add_workflow_history_to_steps",
        "num_history_runs",
        "stream_events",
        "stream_executor_events",
        "store_events",
        "store_media",
        "store_executor_outputs",
        "debug_mode",
        "telemetry",
    )
    defaults: ClassVar[Mapping[str, Any]] = {
        "overwrite_db_session_state": False,
        "add_workflow_history_to_steps": False,
        "num_history_runs": 3,
        "stream_events": False,
        "stream_executor_events": True,
        "store_events": False,
        "store_media": True,
        "store_executor_outputs": True,
        "debug_mode": False,
        "telemetry": True,
    }

    # ---------------------------------------------------------------- identity
    id: str | None = meta_field("identity", "ID", help="Stable id used in API paths and links.", order=1)
    name: str | None = meta_field("identity", "Name", order=2)
    description: str | None = meta_field("identity", "Description", widget="textarea", order=3)
    metadata: dict[str, Any] | None = meta_field("advanced", "Metadata", widget="json", order=90)

    # ---------------------------------------------------------------- input & state
    input_schema: str | dict[str, Any] | None = meta_field(
        "input", "Input schema", help="A schema registered on the instance, or an inline JSON Schema.", widget="schema"
    )
    session_state: dict[str, Any] | None = meta_field("input", "Initial session state", widget="json", order=2)
    overwrite_db_session_state: bool | None = meta_field(
        "input", "Replace the stored session state", widget="switch", order=3
    )
    add_session_state_to_context: bool | None = meta_field(
        "input", "Add the state to the context", widget="switch", order=4
    )
    dependencies: dict[str, Any] | None = meta_field("advanced", "Dependencies", widget="json", order=30)
    add_dependencies_to_context: bool | None = meta_field(
        "advanced", "Add dependencies to the context", widget="switch", order=31
    )

    # ---------------------------------------------------------------- history
    add_workflow_history_to_steps: bool | None = meta_field(
        "history", "Give every step the workflow's history", widget="switch", order=1
    )
    num_history_runs: int | None = meta_field("history", "Runs of history", widget="number", order=2)

    # ---------------------------------------------------------------- runs
    stream: bool | None = meta_field("advanced", "Stream responses", widget="switch", order=50)
    stream_events: bool | None = meta_field("advanced", "Stream intermediate events", widget="switch", order=51)
    stream_executor_events: bool | None = meta_field(
        "advanced", "Stream the executors' events", widget="switch", order=52
    )
    store_events: bool | None = meta_field("advanced", "Store run events", widget="switch", order=53)
    store_media: bool | None = meta_field("advanced", "Store media", widget="switch", order=54)
    store_executor_outputs: bool | None = meta_field(
        "advanced", "Store the executors' outputs", widget="switch", order=55
    )
    debug_mode: bool | None = meta_field("advanced", "Debug mode", widget="switch", order=70)
    telemetry: bool | None = meta_field("advanced", "Telemetry", widget="switch", order=72)

    # ---------------------------------------------------------------- steps
    steps: list[StepTree] | None = meta_field("steps", "Steps", widget="steps", order=1)

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Self:
        return cls.model_validate(data)

    def dump(self) -> dict[str, Any]:
        """``Workflow.to_dict()``'s shape: its always-written settings, the others when set, steps in full."""
        data = self.model_dump(mode="json", exclude_unset=True, by_alias=True, exclude={"steps"})
        data = {key: value for key, value in data.items() if value is not None}
        for name in self.always:
            value = getattr(self, name)
            data[name] = self.defaults[name] if value is None else value
        if self.steps:
            data["steps"] = [step.canonical() for step in self.steps]
        for key, extra in (self.model_extra or {}).items():
            data.setdefault(key, extra)
        return data


@dataclass(frozen=True, slots=True)
class NodeInfo:
    path: str
    node: Node
    depth: int
    """1 for the workflow's own steps."""
    parent: str | None
    """Path of the container the node sits in, ``None`` at the top level."""
    lane: Lane


def iter_nodes(config: WorkflowConfig) -> Iterator[NodeInfo]:
    """Every node, depth first in reading order, with paths such as ``steps[1].choices[2].steps[0]``."""

    def walk(nodes: list[StepTree], prefix: str, lane: Lane, depth: int, parent: str | None) -> Iterator[NodeInfo]:
        for index, node in enumerate(nodes):
            path = f"{prefix}{lane}[{index}]"
            yield NodeInfo(path, node, depth, parent, lane)
            for child_lane in node.lanes:
                yield from walk(node.children(child_lane), f"{path}.", child_lane, depth + 1, path)

    yield from walk(list(config.steps or []), "", "steps", 1, None)


def step_count(config: WorkflowConfig) -> int:
    """Every Step and every container, as the builder counts them."""
    return sum(1 for _ in iter_nodes(config))


def _callable_type(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    return "cel" if isinstance(value, str) and looks_like_cel(value) else "function"


def _json(value: object) -> object:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


__all__ = [
    "CONTAINER_TYPES",
    "HUMAN_REVIEW_SUPPORT",
    "MAX_DEPTH",
    "NODE_MODELS",
    "NODE_TYPES",
    "REVIEW_FLAGS",
    "REVIEW_GROUPS",
    "ConditionNode",
    "HumanReview",
    "LoopNode",
    "Node",
    "NodeInfo",
    "NodeType",
    "ParallelNode",
    "RouterNode",
    "StepNode",
    "StepTree",
    "StepsNode",
    "WorkflowConfig",
    "default_review",
    "iter_nodes",
    "looks_like_cel",
    "review_fields",
    "step_count",
]
