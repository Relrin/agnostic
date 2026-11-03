from agno.workflow import Condition, Loop, Parallel, Router, Step, Workflow

from app.agents import billing_agent, kb_researcher, qa_reviewer, support_triage
from app.functions import check_status, send_reply
from app.teams import escalation_team

ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)

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

ticket_router = Workflow(
    id="ticket-router",
    steps=[
        Step(name="Classify ticket", agent=support_triage),
        Router(
            name="Route by category",
            selector=ROUTE_BY_CATEGORY,
            choices=[
                Step(name="Billing", agent=billing_agent),
                investigate,
                draft_and_review,
            ],
        ),
        Condition(
            name="Needs a human?",
            evaluator='previous_step_content.contains("ESCALATE")',
            steps=[
                Step(name="Escalate", team=escalation_team),
            ],
            else_steps=[
                Step(name="Send reply", executor=send_reply),
            ],
        ),
    ],
)
