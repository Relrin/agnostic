from agno.agent import Agent

from app.registry import models

summarizer = Agent(
    id="summarizer",
    name="summarizer",
    description="Condenses long threads into a short brief.",
    model=models.agnostic_mock,
    instructions="Summarise in at most five bullet points.",
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
    metadata={
        "context_window": 4096,
    },
)
