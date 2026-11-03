from agno.team import Team
from agno.team.mode import TeamMode

from app.agents import billing_agent, qa_reviewer
from app.registry import models

escalation_team = Team(
    id="escalation-team",
    name="escalation-team",
    mode=TeamMode.route,
    respond_directly=True,
    members=[
        billing_agent,
        qa_reviewer,
    ],
    description="Takes escalated tickets and routes them to the right specialist.",
    model=models.agnostic_mock,
    instructions="Billing and refund questions go to billing-agent; complaints about answers go to qa-reviewer.",
    num_history_runs=3,
    store_events=True,
)
