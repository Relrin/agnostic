"""Support triage: Classifies incoming tickets and answers simple ones."""

from agno.agent import Agent

from app.models.mock import MockModel
from app.tools import lookup_order, search_knowledge

support_triage = Agent(
    id="support-triage",
    name="support-triage",
    description="Classifies incoming tickets and answers simple ones.",
    model=MockModel(persona="support-triage"),
    tools=[lookup_order, search_knowledge],
    instructions="Triage the ticket: answer from the help center when you can, otherwise hand off.",
    markdown=True,
)
