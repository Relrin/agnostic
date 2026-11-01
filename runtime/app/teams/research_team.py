"""research-team: coordinates web and knowledge-base research, then summarises."""

from agno.team import Team
from agno.team.mode import TeamMode

from app.agents.kb_researcher import kb_researcher
from app.agents.summarizer import summarizer
from app.agents.web_researcher import web_researcher
from app.models.mock import MockModel

research_team = Team(
    id="research-team",
    name="research-team",
    description="Researches a question across the knowledge base and the web, then writes a brief.",
    mode=TeamMode.coordinate,
    model=MockModel(persona="research-team"),
    members=[kb_researcher, web_researcher, summarizer],
    instructions="Ask kb-researcher first, web-researcher for anything missing, and summarizer for the final brief.",
    store_events=True,
)
