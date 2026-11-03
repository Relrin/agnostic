"""``Team.to_dict()`` as typed fields."""

from __future__ import annotations

from typing import ClassVar, Literal

from agnostic_spec.fields import meta_field
from agnostic_spec.v3_1.base import Kind, SharedConfig
from agnostic_spec.v3_1.refs import MemberRef

TeamMode = Literal["coordinate", "route", "broadcast", "tasks"]
TEAM_MODES: tuple[TeamMode, ...] = ("coordinate", "route", "broadcast", "tasks")
DEFAULT_MAX_ITERATIONS = 10


class TeamConfig(SharedConfig):
    kind: ClassVar[Kind] = "team"

    mode: TeamMode | None = meta_field(
        "team",
        "How the team works together",
        help="`mode` replaces the legacy respond_directly and delegate_to_all_members flags.",
        widget="mode",
        order=1,
    )
    max_iterations: int | None = meta_field(
        "team",
        "Max iterations",
        help="`max_iterations` caps the task loop.",
        widget="number",
        default=DEFAULT_MAX_ITERATIONS,
        order=2,
    )
    determine_input_for_members: bool | None = meta_field(
        "team",
        "Leader writes each member's input",
        help="Off passes the user message through unchanged.",
        widget="switch",
        default=True,
        order=3,
    )
    respond_directly: bool | None = meta_field(
        "team", "Respond directly (legacy)", widget="switch", default=False, legacy=True, order=8
    )
    delegate_to_all_members: bool | None = meta_field(
        "team", "Delegate to all members (legacy)", widget="switch", default=False, legacy=True, order=9
    )

    members: list[MemberRef] | None = meta_field("members", "Members", widget="members", order=1)
    introduction: str | None = meta_field("instructions", "Introduction", widget="textarea", order=4)

    add_team_history_to_members: bool | None = meta_field(
        "context", "Share team history with members", widget="switch", default=False, order=20
    )
    num_team_history_runs: int | None = meta_field(
        "context", "Team history runs shared", widget="number", default=3, order=21
    )
    share_member_interactions: bool | None = meta_field(
        "context", "Share member interactions", widget="switch", default=False, order=22
    )
    add_member_tools_to_context: bool | None = meta_field(
        "context", "Describe member tools to the leader", widget="switch", default=False, order=23
    )
    get_member_information_tool: bool | None = meta_field(
        "tools", "Tool to look up members", widget="switch", default=False, order=3
    )
    add_search_knowledge_instructions: bool | None = meta_field(
        "knowledge", "Explain the search tool in the instructions", widget="switch", default=True, order=8
    )

    def effective_mode(self) -> TeamMode:
        """``mode`` wins; without it agno derives the mode from the legacy flags."""
        if self.mode is not None:
            return self.mode
        if self.respond_directly:
            return "route"
        if self.delegate_to_all_members:
            return "broadcast"
        return "coordinate"
