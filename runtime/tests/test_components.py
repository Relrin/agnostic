"""The sample components the control plane is tested against: refunds pause, tasks-mode teams, workflow loops and
step/route HITL."""

from collections import Counter
from pathlib import Path

import pytest
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.team.mode import TeamMode
from agno.workflow import Loop, Router, Step

from app.agents import AGENTS
from app.agents.support_triage import support_triage
from app.teams import TEAMS
from app.teams.onboarding_team import onboarding_team
from app.workflows import WORKFLOWS
from app.workflows.refund_review import refund_review
from app.workflows.ticket_router import ticket_router


def test_registered_components() -> None:
    assert {agent.id for agent in AGENTS} == {
        "support-triage",
        "billing-agent",
        "kb-researcher",
        "qa-reviewer",
        "web-researcher",
        "summarizer",
    }
    assert {team.id for team in TEAMS} == {"research-team", "escalation-team", "onboarding-team"}
    assert {workflow.id for workflow in WORKFLOWS} == {"ticket-router", "daily-brief", "refund-review"}


def test_every_component_stores_events_for_resume() -> None:
    assert all(component.store_events for component in [*AGENTS, *TEAMS, *WORKFLOWS])


def test_support_triage_pauses_on_refund() -> None:
    run = support_triage.run("order 4471, refund 49 to cus_7")
    assert run.status == RunStatus.paused
    assert [(tool.tool_name, tool.tool_args) for tool in run.tools or []] == [
        ("refund_customer", {"customer_id": "cus_7", "amount": 49.0, "reason": "requested in chat"})
    ]


def test_onboarding_team_works_a_task_list() -> None:
    assert onboarding_team.mode == TeamMode.tasks
    assert [member.id for member in onboarding_team.members] == ["kb-researcher", "summarizer"]
    events = Counter(
        type(event).__name__
        for event in onboarding_team.run("onboard Acme to billing", stream=True, stream_events=True)
    )
    assert events["TaskCreatedEvent"] == 2
    assert events["TaskUpdatedEvent"] >= 2
    assert events["RunCompletedEvent"] == 3  # the two member runs and the team run


def test_refund_review_shape() -> None:
    triage, research, approve = refund_review.steps
    assert isinstance(triage, Step) and triage.agent is support_triage
    assert isinstance(research, Loop) and research.max_iterations == 2
    assert [step.agent.id for step in research.steps] == ["kb-researcher"]
    review = approve.human_review
    assert approve.name == "approve"
    assert (review.requires_confirmation, review.requires_user_input, review.requires_output_review) == (
        True,
        True,
        True,
    )
    assert [(field["name"], field["field_type"]) for field in review.user_input_schema] == [
        ("amount", "float"),
        ("reason", "str"),
    ]


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SqliteDb:
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    monkeypatch.setattr(refund_review, "db", db)
    monkeypatch.setattr(ticket_router, "db", db)
    return db


@pytest.mark.usefixtures("db")
def test_refund_review_confirms_takes_input_then_reviews_output() -> None:
    run = refund_review.run("customer cus_7 wants their money back", session_id="refund-review")
    assert run.status == RunStatus.paused
    (gate,) = run.step_requirements
    assert (gate.step_name, gate.requires_confirmation, gate.requires_user_input) == ("approve", True, True)
    gate.set_user_input(amount=49.0, reason="damaged item")
    gate.confirm()

    run = refund_review.continue_run(run, step_requirements=run.step_requirements)
    assert run.status == RunStatus.paused
    review = run.step_requirements[-1]
    assert review.requires_output_review
    review.confirm()

    run = refund_review.continue_run(run, step_requirements=run.step_requirements)
    assert run.status == RunStatus.completed
    assert run.content == "Refund of 49.00 approved: damaged item."
    assert [step.step_name for step in run.step_results] == ["triage", "research", "approve"]


@pytest.mark.usefixtures("db")
def test_ticket_router_pauses_for_route_selection() -> None:
    router = ticket_router.steps[1]
    assert isinstance(router, Router) and router.human_review.requires_user_input
    run = ticket_router.run("where is my order ord_9?", session_id="ticket-router")
    (pick,) = run.step_requirements
    assert pick.requires_route_selection and pick.available_choices == ["billing", "research"]
    pick.selected_choices = ["research"]
    pick.confirm()

    run = ticket_router.continue_run(run, step_requirements=run.step_requirements)
    assert run.status == RunStatus.completed
    assert str(run.content).startswith("[kb-researcher] ")


@pytest.mark.usefixtures("db")
@pytest.mark.parametrize(
    ("ticket", "iterations"),
    [("search the help center for returns", 1), ("customer cus_7 wants their money back", 2)],
)
def test_refund_review_loop_ends_early_on_a_help_center_article(ticket: str, iterations: int) -> None:
    run = refund_review.run(ticket, session_id=f"loop-{iterations}")
    (research,) = [step for step in run.step_results if step.step_name == "research"]
    assert research.content == f"Loop research completed {iterations} iterations with {iterations} total steps"
