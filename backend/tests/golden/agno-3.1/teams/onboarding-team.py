from agno.team import Team
from agno.team.mode import TeamMode

from app.agents import kb_researcher, summarizer
from app.registry import models

onboarding_team = Team(
    id="onboarding-team",
    name="onboarding-team",
    mode=TeamMode.tasks,
    members=[
        kb_researcher,
        summarizer,
    ],
    description="Plans a new customer's onboarding as a task list: help-center research, then a welcome brief.",
    model=models.agnostic_mock,
    instructions="Create a task for kb-researcher per product area, then one for summarizer to write the brief.",
    num_history_runs=3,
    store_events=True,
)
