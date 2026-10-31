"""Summarizer: Condenses long threads into a short brief."""

from agno.agent import Agent

from app.models.mock import MockModel

summarizer = Agent(
    id="summarizer",
    name="summarizer",
    description="Condenses long threads into a short brief.",
    model=MockModel(persona="summarizer"),
    instructions="Summarise in at most five bullet points.",
    markdown=True,
)
