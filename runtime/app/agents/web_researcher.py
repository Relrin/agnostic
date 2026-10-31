"""Web researcher: Researches public sources (offline stub in this runtime)."""

from agno.agent import Agent

from app.models.mock import MockModel
from app.tools import web_search

web_researcher = Agent(
    id="web-researcher",
    name="web-researcher",
    description="Researches public sources (offline stub in this runtime).",
    model=MockModel(persona="web-researcher"),
    tools=[web_search],
    instructions="Search the web and summarise the three most relevant results.",
    markdown=True,
)
