"""KB researcher: Finds answers in the help-center knowledge base."""

from agno.agent import Agent

from app.models.mock import MockModel
from app.tools import search_knowledge

kb_researcher = Agent(
    id="kb-researcher",
    name="kb-researcher",
    description="Finds answers in the help-center knowledge base.",
    model=MockModel(persona="kb-researcher"),
    tools=[search_knowledge],
    instructions="Search the knowledge base and cite the article you used.",
    markdown=True,
    store_events=True,
)
