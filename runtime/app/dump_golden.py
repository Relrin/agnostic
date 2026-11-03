"""Write agno's serialized form of the runtime's agents and teams as golden files for the control plane.

    uv run python -m app.dump_golden        # from runtime/; `just golden` does the same

Each agent and team becomes ``backend/tests/golden/agno-<major>.<minor>/{agents,teams}/<id>.json``: ``to_dict()``
as sorted, indented JSON. Two extra fixtures built here use every field Studio edits, so a change in how agno
serializes any of them shows up as a diff. The directories are rewritten from scratch, so a removed component
removes its file. agno logs to stdout, so nothing is printed.
"""

import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.team import Team
from agno.team.mode import TeamMode

from app.agents import AGENTS
from app.agents.kb_researcher import kb_researcher
from app.agents.summarizer import summarizer
from app.registry import MODEL_PRESETS, build_memory_manager
from app.schemas import TriageResult
from app.teams import TEAMS
from app.tools import lookup_order, refund_customer, search_knowledge

_major, _minor, *_ = version("agno").split(".")
GOLDEN_DIR = Path(__file__).resolve().parents[2] / "backend" / "tests" / "golden" / f"agno-{_major}.{_minor}"


def _preset(model_id: str) -> Any:
    return next(model for model in MODEL_PRESETS if model.id == model_id)


def full_agent() -> Agent:
    """An agent setting every field the Studio agent form edits."""
    return Agent(
        id="golden-full-agent",
        name="Golden full agent",
        description="Exercises every serializable field Studio edits.",
        role="Triage incoming tickets",
        model=_preset("mock-precise"),
        instructions=["Classify the ticket.", "Escalate refunds over 100 to a human."],
        expected_output="A TriageResult.",
        additional_context="Customers on the gold tier get priority.",
        tools=[lookup_order, search_knowledge, refund_customer],
        tool_call_limit=4,
        output_schema=TriageResult,
        memory_manager=build_memory_manager(None),
        enable_agentic_memory=True,
        update_memory_on_run=True,
        add_memories_to_context=True,
        add_history_to_context=True,
        num_history_runs=5,
        read_chat_history=True,
        enable_session_summaries=True,
        add_session_summary_to_context=True,
        session_state={"tier": "gold", "open_tickets": []},
        add_session_state_to_context=True,
        enable_agentic_state=True,
        add_datetime_to_context=True,
        markdown=True,
        retries=2,
        metadata={"owner": "support"},
        store_events=True,
    )


def tasks_team() -> Team:
    """A tasks-mode team with the iteration and member-input settings changed from their defaults."""
    return Team(
        id="golden-tasks-team",
        name="Golden tasks team",
        description="Works a task list across two members.",
        mode=TeamMode.tasks,
        model=_preset("mock-creative"),
        members=[kb_researcher, summarizer],
        instructions=["Create one task per member.", "Mark the goal complete when every task is done."],
        max_iterations=6,
        determine_input_for_members=False,
        add_history_to_context=True,
        num_history_runs=3,
        markdown=True,
        store_events=True,
    )


def dump(directory: Path) -> list[Path]:
    """Write every golden file under ``directory``, replacing what was there; returns the files written."""
    written: list[Path] = []
    groups = {"agents": [*AGENTS, full_agent()], "teams": [*TEAMS, tasks_team()]}
    for folder, components in groups.items():
        target = directory / folder
        target.mkdir(parents=True, exist_ok=True)
        for stale in target.glob("*.json"):
            stale.unlink()
        for component in components:
            path = target / f"{component.id}.json"
            text = json.dumps(component.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    return written


if __name__ == "__main__":
    dump(GOLDEN_DIR)
