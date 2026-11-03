from agno.team import Team
from agno.team.mode import TeamMode

from app.agents import kb_researcher, summarizer, web_researcher
from app.registry import models

research_team = Team(
    id="research-team",
    name="research-team",
    mode=TeamMode.coordinate,
    members=[
        kb_researcher,
        web_researcher,
        summarizer,
    ],
    description="Researches a question across the knowledge base and the web, then writes a brief.",
    model=models.agnostic_mock,
    instructions="Ask kb-researcher first, web-researcher for anything missing, and summarizer for the final brief.",
    num_history_runs=3,
    store_events=True,
)
