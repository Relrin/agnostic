from agno.workflow import Router, Step, Workflow
from agno.workflow.types import HumanReview

from app.agents import billing_agent, kb_researcher, support_triage

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
            human_review=HumanReview(
                requires_user_input=True,
                user_input_message="Send this ticket to billing or to research?",
            ),
        ),
    ],
    store_events=True,
)
