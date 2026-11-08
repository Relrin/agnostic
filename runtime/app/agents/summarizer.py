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
    store_events=True,
    # The mock model has no window of its own: a small one makes the chat's context meter show a share of it.
    metadata={"context_window": 4096},
)
