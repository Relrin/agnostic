"""escalation-team: routes escalated tickets to billing or QA."""

from agno.team import Team
from agno.team.mode import TeamMode

from app.agents.billing_agent import billing_agent
from app.agents.qa_reviewer import qa_reviewer
from app.models.mock import MockModel

escalation_team = Team(
    id="escalation-team",
    name="escalation-team",
    description="Takes escalated tickets and routes them to the right specialist.",
    mode=TeamMode.route,
    model=MockModel(persona="escalation-team"),
    members=[billing_agent, qa_reviewer],
    instructions="Billing and refund questions go to billing-agent; complaints about answers go to qa-reviewer.",
    store_events=True,
)
