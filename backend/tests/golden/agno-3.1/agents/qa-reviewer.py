from agno.agent import Agent

from app.registry import models

qa_reviewer = Agent(
    id="qa-reviewer",
    name="qa-reviewer",
    description="Reviews draft answers for accuracy and tone.",
    model=models.agnostic_mock,
    instructions="Review the draft. Point out factual errors first, tone second.",
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
