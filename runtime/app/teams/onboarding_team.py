"""onboarding-team: splits an onboarding request into tasks for knowledge-base research and a summary."""

from agno.team import Team
from agno.team.mode import TeamMode

from app.agents.kb_researcher import kb_researcher
from app.agents.summarizer import summarizer
from app.models.mock import MockModel

onboarding_team = Team(
    id="onboarding-team",
    name="onboarding-team",
    description="Plans a new customer's onboarding as a task list: help-center research, then a welcome brief.",
    mode=TeamMode.tasks,
    model=MockModel(persona="onboarding-team"),
    members=[kb_researcher, summarizer],
    instructions="Create a task for kb-researcher per product area, then one for summarizer to write the brief.",
    store_events=True,
)
