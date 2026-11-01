"""ticket-router: triage, then a human picks billing or knowledge-base research (route selection)."""

from agno.workflow import Router, Step, Workflow
from agno.workflow.types import HumanReview

from app.agents.billing_agent import billing_agent
from app.agents.kb_researcher import kb_researcher
from app.agents.support_triage import support_triage

ticket_router = Workflow(
    id="ticket-router",
    name="ticket-router",
    description="Triages a ticket and routes it to billing or to knowledge-base research.",
    steps=[
        Step(name="triage", agent=support_triage),
        Router(
            name="route",
            selector='input.contains("refund") || input.contains("invoice") ? "billing" : "research"',
            choices=[
                Step(name="billing", agent=billing_agent),
                Step(name="research", agent=kb_researcher),
            ],
            # Route selection: the run pauses until someone picks a route. While it's on, agno doesn't evaluate the
            # CEL selector; it stays in the config as the rule to fall back on if route selection is removed.
            human_review=HumanReview(
                requires_user_input=True,
                user_input_message="Send this ticket to billing or to research?",
            ),
        ),
    ],
    store_events=True,
)
