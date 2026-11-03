"""Rules a config must follow beyond its shape. Registry resolution and agno's own strict load come after these."""

from __future__ import annotations

from collections import Counter

from agnostic_spec.diagnostics import Diagnostic
from agnostic_spec.v3_1.base import ComponentConfig, SharedConfig
from agnostic_spec.v3_1.refs import ToolRef, learning_name
from agnostic_spec.v3_1.team import DEFAULT_MAX_ITERATIONS, TeamConfig
from agnostic_spec.v3_1.workflow import (
    CONTAINER_TYPES,
    MAX_DEPTH,
    REVIEW_FLAGS,
    ConditionNode,
    LoopNode,
    NodeInfo,
    ParallelNode,
    RouterNode,
    StepNode,
    WorkflowConfig,
    default_review,
    iter_nodes,
    review_fields,
)


def check(config: ComponentConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    if isinstance(config, SharedConfig):
        found.extend(_shared(config))
        found.extend(_tools(config))
    if isinstance(config, TeamConfig):
        found.extend(_team(config))
    if isinstance(config, WorkflowConfig):
        found.extend(_workflow(config))
    return found


def _shared(config: SharedConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    if config.model is None:
        found.append(
            Diagnostic(
                "model", "warning", "model_missing", "No model is set, so AgentOS falls back to its default model."
            )
        )
    if isinstance(config.instructions, list):
        for index, text in enumerate(config.instructions):
            if not text.strip():
                found.append(
                    Diagnostic(f"instructions[{index}]", "error", "instruction_empty", "This instruction is empty.")
                )
    if config.knowledge is None and (config.add_knowledge_to_context or config.knowledge_filters):
        found.append(
            Diagnostic(
                "knowledge",
                "warning",
                "knowledge_flags_without_knowledge",
                "Knowledge settings are set without a knowledge base.",
            )
        )
    memory_flags = config.enable_agentic_memory or config.update_memory_on_run
    if memory_flags and (config.learning is True or learning_name(config.learning) is not None):
        found.append(
            Diagnostic(
                "learning",
                "info",
                "learning_supersedes_memory",
                "Learning is on, so it manages user memory; the legacy memory flags only apply when learning is off.",
            )
        )
    if config.num_history_runs is not None and not config.add_history_to_context:
        found.append(
            Diagnostic(
                "num_history_runs",
                "info",
                "history_off",
                "History isn't added to the context, so the number of history runs has no effect.",
            )
        )
    return found


def _tools(config: SharedConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    names: Counter[str] = Counter()
    for index, tool in enumerate(config.tools or []):
        if not isinstance(tool, ToolRef):
            continue
        names[tool.name] += 1
        if names[tool.name] == 2:  # noqa: PLR2004
            found.append(
                Diagnostic(f"tools[{index}]", "warning", "tool_duplicate", f"`{tool.name}` is attached twice.")
            )
        if tool.parameters is None:
            found.append(
                Diagnostic(
                    f"tools[{index}]",
                    "error",
                    "tool_without_parameters",
                    f"`{tool.name}` has no parameters, so AgentOS can't rebuild it. Remove it and add it again from "
                    "the registry.",
                )
            )
    return found


def _team(config: TeamConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    members = config.members or []
    if not members:
        found.append(Diagnostic("members", "error", "members_missing", "A team needs at least one member."))
    seen: set[str] = set()
    for index, member in enumerate(members):
        if not member.component_id:
            found.append(
                Diagnostic(f"members[{index}]", "error", "member_without_id", "This member doesn't name a component.")
            )
        elif member.component_id in seen:
            found.append(
                Diagnostic(
                    f"members[{index}]", "error", "member_duplicate", f"`{member.component_id}` is a member twice."
                )
            )
        seen.add(member.component_id)
    if config.max_iterations is not None and config.max_iterations < 1:
        found.append(
            Diagnostic("max_iterations", "error", "max_iterations_invalid", "Max iterations must be at least 1.")
        )
    if config.max_iterations not in {None, DEFAULT_MAX_ITERATIONS} and config.effective_mode() != "tasks":
        found.append(
            Diagnostic("max_iterations", "info", "max_iterations_unused", "Max iterations only applies in tasks mode.")
        )
    if config.mode is not None and (config.respond_directly or config.delegate_to_all_members):
        found.append(
            Diagnostic(
                "mode",
                "warning",
                "legacy_flags_ignored",
                "`mode` replaces respond_directly and delegate_to_all_members; the legacy flags are ignored.",
            )
        )
    return found


def _workflow(config: WorkflowConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    if not config.steps:
        found.append(Diagnostic("steps", "error", "steps_missing", "A workflow needs at least one step."))
    names: dict[str, str] = {}
    step_ids: set[str] = set()
    inside_parallel: set[str] = set()
    for info in iter_nodes(config):
        node = info.node
        if info.parent in inside_parallel or isinstance(node, ParallelNode):
            inside_parallel.add(info.path)
        found.extend(_named(info, names))
        if isinstance(node, StepNode):
            found.extend(_step(info, node, step_ids))
        else:
            found.extend(_container(info))
        found.extend(_review(info, inside_parallel))
        if info.depth > MAX_DEPTH:
            found.append(
                Diagnostic(
                    info.path,
                    "error",
                    "nesting_too_deep",
                    f"Steps can nest at most {MAX_DEPTH} levels deep; this one is at level {info.depth}.",
                )
            )
    return found


def _named(info: NodeInfo, names: dict[str, str]) -> list[Diagnostic]:
    name = info.node.name
    if not name or not name.strip():
        severity = "warning" if info.node.node_type in CONTAINER_TYPES else "error"
        return [
            Diagnostic(
                info.path,
                severity,
                "step_name_missing",
                "Give this step a name: runs, stats and pins refer to steps by name.",
            )
        ]
    if name in names:
        return [Diagnostic(info.path, "error", "step_name_duplicate", f"Another step is already called `{name}`.")]
    names[name] = info.path
    return []


def _step(info: NodeInfo, node: StepNode, step_ids: set[str]) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    executors = node.executors()
    if not executors:
        found.append(
            Diagnostic(
                info.path,
                "error",
                "executor_missing",
                "Pick what this step runs: an agent, a team, a workflow or a function.",
            )
        )
    elif len(executors) > 1:
        fields = ", ".join(field for field, _ in executors)
        found.append(
            Diagnostic(info.path, "error", "executor_multiple", f"A step runs exactly one executor; it names {fields}.")
        )
    if node.step_id:
        if node.step_id in step_ids:
            found.append(
                Diagnostic(
                    info.path, "error", "step_id_duplicate", f"Another step already has the id `{node.step_id}`."
                )
            )
        step_ids.add(node.step_id)
    return found


def _container(info: NodeInfo) -> list[Diagnostic]:
    node = info.node
    found: list[Diagnostic] = []
    if isinstance(node, RouterNode):
        if not node.choices:
            found.append(Diagnostic(info.path, "error", "choices_missing", "A router needs at least one choice."))
        if not node.selector and not node.review()["requires_user_input"]:
            found.append(
                Diagnostic(
                    f"{info.path}.selector",
                    "error",
                    "selector_missing",
                    "Set a selector, or let a person pick the route.",
                )
            )
    elif isinstance(node, LoopNode):
        if node.max_iterations is not None and node.max_iterations < 1:
            found.append(
                Diagnostic(
                    f"{info.path}.max_iterations",
                    "error",
                    "max_iterations_invalid",
                    "Max iterations must be at least 1.",
                )
            )
    elif isinstance(node, ConditionNode) and isinstance(node.evaluator, bool) and node.else_steps and node.evaluator:
        found.append(
            Diagnostic(
                f"{info.path}.evaluator",
                "info",
                "else_unreachable",
                "The evaluator is always true, so the else branch only runs when someone rejects the condition.",
            )
        )
    if not isinstance(node, RouterNode) and not node.children(node.lanes[0]):
        found.append(Diagnostic(info.path, "error", "children_missing", f"This {node.node_type.lower()} has no steps."))
    return found


def _review(info: NodeInfo, inside_parallel: set[str]) -> list[Diagnostic]:
    node = info.node
    review = node.review()
    defaults = default_review(node.node_type)
    allowed = review_fields(node.node_type)
    found: list[Diagnostic] = []
    flags = [flag for flag in REVIEW_FLAGS if review.get(flag)]
    if flags and info.parent is not None and info.parent in inside_parallel:
        found.append(
            Diagnostic(
                f"{info.path}.human_review",
                "error",
                "review_in_parallel",
                "Steps inside a Parallel run at once and can't pause for a person.",
            )
        )
    for field, value in review.items():
        if field in allowed or field not in defaults or value == defaults[field]:
            continue
        if field in REVIEW_FLAGS:
            found.append(
                Diagnostic(
                    f"{info.path}.human_review.{field}",
                    "error",
                    "review_unsupported",
                    f"A {node.node_type} can't use `{field}`.",
                )
            )
        else:
            found.append(
                Diagnostic(
                    f"{info.path}.human_review.{field}",
                    "warning",
                    "review_option_unused",
                    f"`{field}` has no effect on a {node.node_type}.",
                )
            )
    if review.get("requires_output_review") and review.get("requires_iteration_review"):
        found.append(
            Diagnostic(
                f"{info.path}.human_review",
                "error",
                "review_exclusive",
                "Output review and iteration review can't both be on.",
            )
        )
    return found
