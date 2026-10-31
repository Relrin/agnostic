"""ticket-router: triage, then route to billing or knowledge-base research by a CEL expression."""

from agno.workflow import Router, Step, Workflow

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
        ),
    ],
)
