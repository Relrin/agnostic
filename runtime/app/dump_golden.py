"""Write agno's serialized form of the runtime's agents, teams and workflows as golden files for the control plane.

    uv run python -m app.dump_golden        # from runtime/; `just golden` does the same

Each component becomes ``backend/tests/golden/agno-<major>.<minor>/{agents,teams,workflows}/<id>.json``:
``to_dict()`` as sorted, indented JSON. Extra fixtures built here use every field Studio edits, so a change in how
agno serializes any of them shows up as a diff. ``prototype/ticket-router.json`` is the ticket router of the Studio
design, built exactly as its code reads; the control plane checks that the code it generates for this config is
that code. The directories are rewritten from scratch, so a removed component removes its file. agno logs to stdout,
so nothing is printed.
"""

import json
import re
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.team import Team
from agno.team.mode import TeamMode
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import HumanReview

from app.agents import AGENTS
from app.agents.billing_agent import billing_agent
from app.agents.kb_researcher import kb_researcher
from app.agents.qa_reviewer import qa_reviewer
from app.agents.summarizer import summarizer
from app.agents.support_triage import support_triage
from app.functions import check_status, needs_escalation, send_reply
from app.registry import MODEL_PRESETS, build_memory_manager
from app.schemas import TriageResult
from app.teams import TEAMS
from app.teams.escalation_team import escalation_team
from app.teams.research_team import research_team
from app.tools import lookup_order, refund_customer, search_knowledge
from app.workflows import WORKFLOWS
from app.workflows.daily_brief import daily_brief

_major, _minor, *_ = version("agno").split(".")
_GENERATED_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
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


def full_workflow() -> Workflow:
    """A workflow using every primitive, every executor kind and the review options each node supports."""
    return Workflow(
        id="golden-full-workflow",
        name="Golden full workflow",
        description="Exercises every primitive and review option Studio edits.",
        input_schema=TriageResult,
        session_state={"attempts": 0},
        add_workflow_history_to_steps=True,
        num_history_runs=2,
        store_events=True,
        steps=[
            Step(
                name="Classify",
                step_id="classify",
                agent=support_triage,
                max_retries=1,
                human_review=HumanReview(
                    requires_user_input=True,
                    user_input_message="Anything the classifier should know?",
                    user_input_schema=[{"name": "note", "field_type": "str", "description": "A hint"}],
                    timeout=3600,
                    on_timeout="skip",
                ),
            ),
            Steps(
                name="Prepare",
                steps=[Step(name="Research", team=research_team), Step(name="Brief", workflow=daily_brief)],
                human_review=HumanReview(requires_confirmation=True, confirmation_message="Prepare a brief?"),
            ),
            Parallel(
                Step(name="Look up", agent=kb_researcher),
                Step(name="Status", executor=check_status),
                name="Gather",
            ),
            Router(
                name="Route",
                selector='input.contains("refund") ? "Refund" : "Answer"',
                choices=[
                    Step(name="Refund", agent=billing_agent, skip_on_failure=True),
                    Loop(
                        name="Answer",
                        steps=[Step(name="Draft", agent=support_triage), Step(name="Review", agent=qa_reviewer)],
                        end_condition='last_step_content.contains("APPROVED")',
                        max_iterations=4,
                        forward_iteration_output=True,
                        human_review=HumanReview(requires_iteration_review=True),
                    ),
                ],
                human_review=HumanReview(requires_output_review=True, output_review_message="Send this answer?"),
            ),
            Condition(
                name="Escalate?",
                evaluator=needs_escalation,
                steps=[Step(name="Escalate", team=escalation_team)],
                else_steps=[Step(name="Reply", executor=send_reply)],
                human_review=HumanReview(on_error="fail"),
            ),
        ],
    )


# The ticket router as the Studio design draws it; the control plane's generated code must read the same.
ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)


def prototype_ticket_router() -> Workflow:
    investigate = Parallel(
        Step(name="Search KB", agent=kb_researcher),
        Step(name="Check status page", executor=check_status),
        name="Investigate",
    )
    draft_and_review = Loop(
        name="Draft & review",
        steps=[
            Step(name="Draft reply", agent=support_triage),
            Step(name="Review tone", agent=qa_reviewer),
        ],
        end_condition='last_step_content.contains("APPROVED")',
        max_iterations=3,
    )
    return Workflow(
        id="ticket-router",
        steps=[
            Step(name="Classify ticket", agent=support_triage),
            Router(
                name="Route by category",
                selector=ROUTE_BY_CATEGORY,
                choices=[Step(name="Billing", agent=billing_agent), investigate, draft_and_review],
            ),
            Condition(
                name="Needs a human?",
                evaluator='previous_step_content.contains("ESCALATE")',
                steps=[Step(name="Escalate", team=escalation_team)],
                else_steps=[Step(name="Send reply", executor=send_reply)],
            ),
        ],
    )


def _stable(value: Any) -> Any:
    """agno gives a step built without a ``step_id`` a random one; the files store none, as a Studio config does."""
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if not isinstance(value, dict):
        return value
    stable = {key: _stable(item) for key, item in value.items()}
    if stable.get("type") == "Step" and _GENERATED_ID.fullmatch(str(stable.get("step_id") or "")):
        stable["step_id"] = None
    return stable


def dump(directory: Path) -> list[Path]:
    """Write every golden file under ``directory``, replacing what was there; returns the files written."""
    written: list[Path] = []
    groups: dict[str, list[Any]] = {
        "agents": [*AGENTS, full_agent()],
        "teams": [*TEAMS, tasks_team()],
        "workflows": [*WORKFLOWS, full_workflow()],
        "prototype": [prototype_ticket_router()],
    }
    for folder, components in groups.items():
        target = directory / folder
        target.mkdir(parents=True, exist_ok=True)
        for stale in target.glob("*.json"):
            stale.unlink()
        for component in components:
            path = target / f"{component.id}.json"
            text = json.dumps(_stable(component.to_dict()), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(path)
    return written


if __name__ == "__main__":
    dump(GOLDEN_DIR)
