"""Rules a config must follow beyond its shape. Registry resolution and agno's own strict load come after these."""

from __future__ import annotations

from collections import Counter

from agnostic_spec.diagnostics import Diagnostic
from agnostic_spec.v3_1.base import ComponentConfig, SharedConfig
from agnostic_spec.v3_1.refs import ToolRef, learning_name
from agnostic_spec.v3_1.team import DEFAULT_MAX_ITERATIONS, TeamConfig


def check(config: ComponentConfig) -> list[Diagnostic]:
    found: list[Diagnostic] = []
    if isinstance(config, SharedConfig):
        found.extend(_shared(config))
        found.extend(_tools(config))
    if isinstance(config, TeamConfig):
        found.extend(_team(config))
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
