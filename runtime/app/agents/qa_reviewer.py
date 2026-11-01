"""QA reviewer: Reviews draft answers for accuracy and tone."""

from agno.agent import Agent

from app.models.mock import MockModel

qa_reviewer = Agent(
    id="qa-reviewer",
    name="qa-reviewer",
    description="Reviews draft answers for accuracy and tone.",
    model=MockModel(persona="qa-reviewer"),
    instructions="Review the draft. Point out factual errors first, tone second.",
    markdown=True,
    store_events=True,
)
