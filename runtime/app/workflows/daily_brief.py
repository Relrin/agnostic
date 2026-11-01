"""daily-brief: research the day's topics, then summarise. Meant to run on a schedule."""

from agno.workflow import Step, Workflow

from app.agents.summarizer import summarizer
from app.teams.research_team import research_team

daily_brief = Workflow(
    id="daily-brief",
    name="daily-brief",
    description="Collects the day's open questions and writes a short brief (scheduled every morning).",
    steps=[
        Step(name="research", team=research_team),
        Step(name="brief", agent=summarizer),
    ],
    store_events=True,
)
