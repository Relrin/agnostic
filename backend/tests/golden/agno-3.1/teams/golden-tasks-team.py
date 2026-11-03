from agno.team import Team
from agno.team.mode import TeamMode

from app.agents import kb_researcher, summarizer
from app.registry import models

golden_tasks_team = Team(
    id="golden-tasks-team",
    name="Golden tasks team",
    mode=TeamMode.tasks,
    max_iterations=6,
    determine_input_for_members=False,
    members=[
        kb_researcher,
        summarizer,
    ],
    description="Works a task list across two members.",
    model=models.mock_creative,
    instructions=[
        "Create one task per member.",
        "Mark the goal complete when every task is done.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
